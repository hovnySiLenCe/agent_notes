"""AT-SPI tree helpers. Every call here is a blocking D-Bus round-trip: run on the worker thread only."""
from __future__ import annotations

import time
from typing import Iterator

import gi

gi.require_version('Atspi', '2.0')
from gi.repository import Atspi  # noqa: E402

# libatspi's default lets calls to an app block for up to 15 s after it starts (then 25 s D-Bus timeouts).
# A busy or just-launched app must never freeze capture/fill: fail fast and fall back instead.
Atspi.set_timeout(1000, 1000)

S = Atspi.StateType
T = Atspi.Text
OBJ = '\ufffc'   # embedded-object placeholder inside hypertext


def find_app(pid: int):
    desk = Atspi.get_desktop(0)
    for i in range(desk.get_child_count()):
        a = desk.get_child_at_index(i)
        if a is not None and a.get_process_id() == pid:
            return a
    return None


def find_frame(app, title: str):
    """The top-level frame of `app` matching the X window: the ACTIVE one, else by title."""
    frames = [f for f in (app.get_child_at_index(i) for i in range(app.get_child_count())) if f is not None]
    for f in frames:
        if f.get_state_set().contains(S.ACTIVE):
            return f
    for f in frames:
        if title and (f.get_name() or '') == title:
            return f
    return frames[0] if frames else None


def frame_for(pid: int | None, title: str):
    if not pid:
        return None
    app = find_app(pid)
    if app is None:
        return None
    try:
        app.clear_cache()   # we don't run a GLib loop, so cached children may be stale
    except Exception:
        pass
    return find_frame(app, title)


def walk(root, deadline: float, max_nodes: int = 20000, prune_hidden: bool = True
         ) -> Iterator[tuple[object, tuple[int, ...], bool]]:
    """Pre-order (= document order) walk yielding (node, child-index path from root, inside web content)."""
    stack = [(root, (), False)]
    seen = 0
    while stack:
        node, path, in_doc = stack.pop()
        seen += 1
        if seen > max_nodes or time.monotonic() > deadline:
            return
        try:
            role = node.get_role_name()
        except Exception:
            continue
        in_doc = in_doc or role == 'document web'
        yield node, path, in_doc
        try:
            if prune_hidden and path and not node.get_state_set().contains(S.SHOWING):
                continue
            count = node.get_child_count()
        except Exception:
            continue
        kids = []
        for k in range(count):
            try:
                c = node.get_child_at_index(k)
            except Exception:
                c = None
            if c is not None:
                kids.append((c, path + (k,), in_doc))
        stack.extend(reversed(kids))


def text_of(node, start: int = 0, end: int = -1) -> str:
    n = T.get_character_count(node)
    end = n if end < 0 else min(end, n)
    return T.get_text(node, max(0, start), end)


def doc_url(node) -> str:
    n = node
    while n is not None:
        try:
            if n.get_role_name() == 'document web':
                for key in ('DocURL', 'URI', 'URL'):
                    try:
                        v = Atspi.Document.get_document_attribute_value(n, key)
                    except Exception:
                        v = None
                    if v:
                        return v
            n = n.get_parent()
        except Exception:
            return ''
    return ''
