"""Screen rectangles (physical px) for character ranges, one rect per visual line. Worker thread only."""
from __future__ import annotations

import unicodedata

from Xlib import error

from ..x11 import display as xd
from .tree import OBJ, Atspi, T

Rect = tuple[int, int, int, int]   # x, y, w, h
EMPTY: Rect = (0, 0, 0, 0)


def _lines_to_rects(lines: dict[int, list[int]]) -> list[Rect]:
    return [(a, b, c - a, d - b) for a, b, c, d in lines.values()]


def text_rects(node, start: int, end: int) -> list[Rect]:
    """Generic toolkits (Firefox, Chromium/Electron, GTK, Qt): per-char extents are correct."""
    text = T.get_text(node, start, end)
    lines: dict[int, list[int]] = {}
    for k in range(start, end):
        if k - start < len(text) and (text[k - start] == OBJ or text[k - start] == '\n'):
            continue                  # embedded objects are measured through their own node
        c = T.get_character_extents(node, k, Atspi.CoordType.SCREEN)
        if c.width <= 0:
            continue
        r = lines.setdefault(c.y, [c.x, c.y, c.x + c.width, c.y + c.height])
        r[0], r[2], r[3] = min(r[0], c.x), max(r[2], c.x + c.width), max(r[3], c.y + c.height)
    return _lines_to_rects(lines)


def display_cells(ch: str) -> int:
    return 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1


def vte_rects(term, xid: int, start: int, end: int) -> list[Rect]:
    """VTE (gnome-terminal & co.) reports unscaled window-relative coords and counts wide chars as one cell:
    take the row (y) from VTE, compute x from display width, then scale and offset by the real X window."""
    frame = term
    while frame is not None and frame.get_role_name() != 'frame':
        frame = frame.get_parent()
    try:
        win = xd.get().create_resource_object('window', xid)
        geo = win.get_geometry()
        origin = win.translate_coords(xd.root(), 0, 0)
    except error.XError:
        return []
    fw = Atspi.Component.get_extents(frame, Atspi.CoordType.WINDOW).width if frame is not None else 0
    scale = round(geo.width / fw) if fw else 1
    text = T.get_text(term, 0, T.get_character_count(term))
    lines: dict[int, list[int]] = {}
    line_starts: dict[int, object] = {}
    for k in range(start, min(end, len(text))):
        if text[k] == '\n':
            continue
        ls = text.rfind('\n', 0, k) + 1
        e0 = line_starts.get(ls)
        if e0 is None:
            e0 = line_starts[ls] = T.get_character_extents(term, ls, Atspi.CoordType.WINDOW)
        x = e0.x + sum(display_cells(c) for c in text[ls:k]) * e0.width
        r = lines.setdefault(e0.y, [x, e0.y, x, e0.y + e0.height])
        r[0], r[2] = min(r[0], x), max(r[2], x + display_cells(text[k]) * e0.width)
    ox, oy = -origin.x, -origin.y
    return [(ox + x * scale, oy + y * scale, w * scale, h * scale) for x, y, w, h in _lines_to_rects(lines)]


def node_rect(node) -> Rect | None:
    try:
        e = Atspi.Component.get_extents(node, Atspi.CoordType.SCREEN)
    except Exception:
        return None
    return (e.x, e.y, e.width, e.height) if e.width > 0 and e.height > 0 else None


def intersect(a: Rect, b: Rect) -> Rect | None:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    return (x0, y0, x1 - x0, y1 - y0) if x1 > x0 and y1 > y0 else None


def visible_area(node) -> Rect | None:
    """Intersection of the extents of the node's containers up to its window: text scrolled out of a scroll
    pane still reports on-screen-looking coordinates, but lies outside its container's box.
    Returns None when nothing is known, EMPTY when the node is scrolled out of view completely.

    Web content stops at its outermost document: the browser/editor UI around it adds nothing the window rect
    doesn't, and Electron apps report their native views in logical pixels but web content in physical ones
    (at 2x scaling the two never intersect)."""
    clip: Rect | None = None
    doc_clip: Rect | None = None                   # clip as of the outermost web document passed so far
    n = node.get_parent()
    while n is not None:
        try:
            role = n.get_role_name()
        except Exception:
            break
        if role == 'application':
            break
        r = node_rect(n)
        if r is not None:                          # zero-size wrappers (display: contents …) don't clip
            clip = r if clip is None else intersect(clip, r)
            if clip is None:
                return EMPTY if doc_clip is None else doc_clip
        if role == 'document web':
            doc_clip = clip
        if role == 'frame':
            break
        n = n.get_parent()
    return clip if doc_clip is None else doc_clip


def scroll_pane(node) -> Rect | None:
    """Visible area of the scroll pane `node` moves in: the first container up the tree that its content
    overflows (the child on the way extends past its top or bottom), clipped by the containers around it.
    Unlike visible_area(), this box stays put while the content scrolls. None if no such container."""
    child = node_rect(node)
    n = node.get_parent()
    while n is not None and child is not None:
        try:
            role = n.get_role_name()
        except Exception:
            return None
        if role in ('application', 'frame'):
            return None
        r = node_rect(n)
        if r is not None:
            if child[1] < r[1] - 2 or child[1] + child[3] > r[1] + r[3] + 2:
                outer = visible_area(n)
                return r if outer is None else (intersect(r, outer) or EMPTY)
            child = r
        n = n.get_parent()
    return None


SCALES = (1.0, 2.0, 1.5, 1.25, 1.75, 3.0)


def box_scale(node, offset: int) -> float:
    """Factor from the node's box coordinates to its character coordinates. Firefox at 2x desktop scaling
    reports characters in physical pixels but boxes (its own and its containers') in logical ones; Chromium
    reports both in physical pixels. Found by which scaling of the node's own box contains the character."""
    r = node_rect(node)
    try:
        c = T.get_character_extents(node, offset, Atspi.CoordType.SCREEN)
    except Exception:
        return 1.0
    if r is None or c.width <= 0:
        return 1.0
    cx, cy = c.x + c.width / 2, c.y + c.height / 2
    for k in SCALES:
        if r[0] * k - 2 <= cx <= (r[0] + r[2]) * k + 2 and r[1] * k - 2 <= cy <= (r[1] + r[3]) * k + 2:
            return k
    return 1.0


def scaled(r: Rect | None, k: float) -> Rect | None:
    if r is None or r == EMPTY or k == 1.0:
        return r
    return (round(r[0] * k), round(r[1] * k), round(r[2] * k), round(r[3] * k))
