"""Find a stored annotation's quote again in the live accessibility tree. Worker thread only.

Fast path: the child-index path and offsets recorded at capture time still point at the same text.
Slow path: search the text nodes (starting from the web document the path went through) for the quote,
using the captured prefix/suffix to choose between repeated occurrences.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from ...core.anchor import find_quote, normalize, parts
from ..x11 import windows
from .geometry import node_rect
from .tree import OBJ, S, T, find_app, walk


@dataclass
class Segment:
    node: object
    start: int
    end: int
    text: str           # node text in [start, end) when located: if it changes, locate again
    terminal: bool = False


def _norm(s: str) -> str:
    return normalize(s)[0].strip()


def _text(node) -> str | None:
    try:
        return T.get_text(node, 0, T.get_character_count(node))
    except Exception:
        return None       # not a Text object, or gone


def frames_for(pid: int | None, xid: int) -> list:
    """The app's top-level frames, the one showing X window `xid` first (matched by title, then by size)."""
    app = find_app(pid) if pid else None
    if app is None:
        return []
    try:
        app.clear_cache()
    except Exception:
        pass
    frames = [f for f in (app.get_child_at_index(i) for i in range(app.get_child_count())) if f is not None]
    info = windows.info(xid)
    title = info.title if info else ''
    rect = windows.client_rect(xid)

    def rank(f):
        try:
            name = f.get_name() or ''
            r = node_rect(f)
            active = f.get_state_set().contains(S.ACTIVE)
        except Exception:
            return (0, 0, 0)
        same_size = bool(r and rect and abs(r[2] - rect[2]) <= 4 and abs(r[3] - rect[3]) <= 4)
        return (bool(title) and name == title, same_size, active)
    return sorted(frames, key=rank, reverse=True)


def node_at(root, path) -> tuple[object | None, object | None, tuple]:
    """(node at child-index `path` or None, deepest 'document web' passed on the way, that document's path)."""
    n, doc, doc_path = root, None, ()
    for depth, k in enumerate(path):
        try:
            n = n.get_child_at_index(k)
            if n is None:
                return None, doc, doc_path
            if n.get_role_name() == 'document web' and doc is None:
                doc, doc_path = n, tuple(path[:depth + 1])
        except Exception:
            return None, doc, doc_path
    return n, doc, doc_path


def _between(nodes: list, first: tuple, last: tuple) -> list[Segment]:
    """Whole text nodes strictly between two paths in document order, minus the ancestors of either end
    (an ancestor's text also covers the parts before the selection start / after its end)."""
    out = []
    for node, path, text in nodes:
        if first < path < last and path != last[:len(path)] and path != first[:len(path)] and text.replace(OBJ, '').strip():
            out.append(Segment(node, 0, len(text), text))
    return out


def _fast_path(frame, anchor: dict, quote: str) -> list[Segment] | None:
    path, end_path = anchor.get('path'), anchor.get('end_path')
    if path is None or anchor.get('start') is None or end_path is None:
        return None       # (no end recorded: the quote came from PRIMARY and is searched for)
    node, _, _ = node_at(frame, path)
    text = _text(node) if node is not None else None
    if text is None:
        return None
    s, e = anchor['start'], anchor.get('end', 0)
    terminal = anchor.get('role') == 'terminal'
    if end_path == path:
        if _norm(text[s:e]) == _norm(quote):
            return [Segment(node, s, e, text[s:e], terminal)]
        return None
    ps = parts(quote)
    last, _, _ = node_at(frame, end_path or [])
    last_text = _text(last) if last is not None else None
    if not ps or last_text is None or not _norm(text[s:]).startswith(_norm(ps[0])) \
            or not _norm(last_text[:e]).endswith(_norm(ps[-1])):
        return None
    return [Segment(node, s, len(text), text[s:])]  # middle + last filled in by the caller's walk


def locate(pid: int | None, xid: int, anchor: dict, quote: str, budget: float = 0.8) -> list[Segment] | None:
    if anchor.get('method') != 'atspi' or not quote.strip():
        return None
    deadline = time.monotonic() + budget
    frames = frames_for(pid, xid)
    if not frames:
        return None
    frame = frames[0]
    path = tuple(anchor.get('path') or ())
    end_path = tuple(anchor.get('end_path') or path)
    fast = _fast_path(frame, anchor, quote)
    if fast is not None and end_path == path:
        return fast

    # Search below the web document the capture went through (much smaller than the whole window), else everywhere.
    _, doc, doc_path = node_at(frame, path)
    roots = [(doc, doc_path)] if doc is not None else []
    roots += [(f, ()) for f in frames]
    for root, prefix in roots:
        nodes = []
        for node, rel, _ in walk(root, deadline):
            text = _text(node)
            if text and text.replace(OBJ, '').strip():
                nodes.append((node, prefix + rel, text))
        if fast is not None and root is doc:
            last = next(((n, p, t) for n, p, t in nodes if p == end_path), None)
            if last is not None:
                return fast + _between(nodes, path, end_path) + \
                    [Segment(last[0], 0, anchor.get('end', 0), last[2][:anchor.get('end', 0)])]
        found = _search(nodes, anchor, quote, path)
        if found:
            return found
        if time.monotonic() > deadline:
            break
    return None


def _search(nodes: list, anchor: dict, quote: str, path: tuple) -> list[Segment] | None:
    prefix, suffix = anchor.get('prefix', ''), anchor.get('suffix', '')
    terminal = anchor.get('role') == 'terminal'
    best = None
    for node, p, text in nodes:
        hit = find_quote(text, quote, prefix, suffix, anchor.get('start') if p == path else None)
        if hit:
            key = (hit[2], p == path, len(p))      # context agreement, same place as before, deepest node
            if best is None or key > best[0]:
                best = (key, node, hit, text)
    if best is not None:
        _, node, (s, e, _), text = best
        try:
            terminal = terminal or node.get_role_name() == 'terminal'
        except Exception:
            pass
        return [Segment(node, s, e, text[s:e], terminal)]
    ps = parts(quote)
    if len(ps) < 2:
        return None
    # The quote spans several elements: first part (matched with the prefix), last part after it (with the suffix).
    first = None
    for i, (node, p, text) in enumerate(nodes):
        hit = find_quote(text, ps[0], prefix, '')
        if hit and (first is None or hit[2] > first[0]):
            first = (hit[2], i, hit)
    if first is None:
        return None
    _, i0, (s0, _, _) = first
    for j in range(i0 + 1, min(len(nodes), i0 + 400)):
        node, p, text = nodes[j]
        hit = find_quote(text, ps[-1], '', suffix)
        if hit:
            n0, p0, t0 = nodes[i0]
            return [Segment(n0, s0, len(t0), t0[s0:])] + _between(nodes, p0, p) + \
                [Segment(node, 0, hit[1], text[:hit[1]])]
    return None


def scroll_into_view(seg: Segment) -> bool:
    from .tree import Atspi
    try:
        if T.scroll_substring_to(seg.node, seg.start, seg.end, Atspi.ScrollType.ANYWHERE):
            return True
    except Exception:
        pass
    try:
        return bool(Atspi.Component.scroll_to(seg.node, Atspi.ScrollType.ANYWHERE))
    except Exception:
        return False


def anchor_from_text(pid: int | None, xid: int, quote: str, budget: float = 1.0) -> dict | None:
    """An anchor for a quote that was captured as plain text (the app didn't report its selection offsets):
    find the text in the window's tree. Shown (visible) parts of the window are searched first."""
    if not quote.strip():
        return None
    frames = frames_for(pid, xid)
    if not frames:
        return None
    deadline = time.monotonic() + budget
    nodes = []
    for node, path, _ in walk(frames[0], deadline):
        text = _text(node)
        if text and text.replace(OBJ, '').strip():
            nodes.append((node, path, text))
    segs = _search(nodes, {}, quote, ())
    if not segs:
        return None
    paths = {id(n): (p, t) for n, p, t in nodes}
    (p0, t0), (p1, t1) = paths[id(segs[0].node)], paths[id(segs[-1].node)]
    s, e = segs[0].start, segs[-1].end
    try:
        role = segs[0].node.get_role_name()
    except Exception:
        role = ''
    return {'method': 'atspi', 'located_by': 'text', 'path': list(p0), 'start': s, 'end_path': list(p1), 'end': e,
            'prefix': t0[max(0, s - 40):s].replace(OBJ, ''), 'suffix': t1[e:e + 40].replace(OBJ, ''), 'role': role}


def app_accessible(pid: int | None) -> bool:
    """Does the app expose an accessibility tree at all?"""
    return bool(pid) and find_app(pid) is not None
