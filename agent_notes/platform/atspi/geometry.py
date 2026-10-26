"""Screen rectangles (physical px) for character ranges, one rect per visual line. Worker thread only."""
from __future__ import annotations

import unicodedata

from Xlib import error

from ..x11 import display as xd
from .tree import Atspi, T

Rect = tuple[int, int, int, int]   # x, y, w, h


def _lines_to_rects(lines: dict[int, list[int]]) -> list[Rect]:
    return [(a, b, c - a, d - b) for a, b, c, d in lines.values()]


def text_rects(node, start: int, end: int) -> list[Rect]:
    """Generic toolkits (Firefox, Chromium/Electron, GTK, Qt): per-char extents are correct."""
    lines: dict[int, list[int]] = {}
    for k in range(start, end):
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
    for k in range(start, min(end, len(text))):
        if text[k] == '\n':
            continue
        ls = text.rfind('\n', 0, k) + 1
        e0 = T.get_character_extents(term, ls, Atspi.CoordType.WINDOW)
        x = e0.x + sum(display_cells(c) for c in text[ls:k]) * e0.width
        r = lines.setdefault(e0.y, [x, e0.y, x, e0.y + e0.height])
        r[0], r[2] = min(r[0], x), max(r[2], x + display_cells(text[k]) * e0.width)
    ox, oy = -origin.x, -origin.y
    return [(ox + x * scale, oy + y * scale, w * scale, h * scale) for x, y, w, h in _lines_to_rects(lines)]
