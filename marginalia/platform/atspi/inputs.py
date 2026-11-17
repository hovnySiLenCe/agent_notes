"""Locate and focus the agent's chat input box inside a window."""
from __future__ import annotations

import re
import time

from .tree import Atspi, S, frame_for, walk

_CHAT_HINT = re.compile(r'chat|message|prompt|ask|reply|send|claude|copilot|gpt|gemini|输入|消息|提问|发送|对话', re.I)


def _common_prefix(a: tuple, b: list) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


_last: dict[tuple, tuple] = {}         # (pid, xid) -> path of the input box chosen last time in that window
                                       # (by window, not title: VS Code's title changes with every open file)


def _usable(node) -> bool:
    try:
        st = node.get_state_set()
        return st.contains(S.EDITABLE) and st.contains(S.FOCUSABLE) and 'Text' in (node.get_interfaces() or [])
    except Exception:
        return False


def find_input(pid: int | None, title: str, anchor_path: list | None, budget: float = 1.2, xid: int = 0,
               hint: list | None = None):
    """(node, path) of the chat input box, or None. Editable text boxes inside web content (never browser chrome
    such as the URL bar), ranked by: same document as the annotated text > looks like a chat box > already
    focused > lowest on screen. The box found last time in this window (or `hint`, the caller's memory of it,
    which survives helper restarts) is tried first: walking the whole tree takes a quarter to a full second."""
    frame = frame_for(pid, title)
    if frame is None:
        return None
    from .locate import node_at
    for cached in (_last.get((pid, xid)), hint):
        if not cached:
            continue
        cached = tuple(cached)
        node, _, doc = node_at(frame, cached)
        same_doc = not anchor_path or node_at(frame, anchor_path)[2] in ((), doc)
        if node is not None and same_doc and _usable(node):
            _last[(pid, xid)] = cached
            return node, cached
    found = _search(frame, anchor_path, budget)
    if found is not None:
        _last[(pid, xid)] = tuple(found[1])
    return found


def _search(frame, anchor_path: list | None, budget: float):
    for prune in (True, False):        # visible inputs first; then allow off-screen ones
        best, best_score = None, None
        for node, path, in_doc in walk(frame, time.monotonic() + budget, prune_hidden=prune):
            if not in_doc:
                continue
            try:
                st = node.get_state_set()
                if not (st.contains(S.EDITABLE) and st.contains(S.FOCUSABLE)):
                    continue
                if 'Text' not in (node.get_interfaces() or []):
                    continue
                y = Atspi.Component.get_extents(node, Atspi.CoordType.SCREEN).y
                name = node.get_name() or ''
            except Exception:
                continue
            score = (_common_prefix(path, anchor_path or []), bool(_CHAT_HINT.search(name)),
                     st.contains(S.FOCUSED), y)
            if best_score is None or score > best_score:
                best, best_score = (node, path), score
        if best is not None:
            return best
    return None


def focus_input(pid: int | None, title: str, anchor_path: list | None, xid: int = 0,
                hint: list | None = None) -> dict | None:
    """Focus the chat input: {'name', 'path', 'grabbed' (focus had to be moved there)} or None."""
    found = find_input(pid, title, anchor_path, xid=xid, hint=hint)
    if found is None:
        return None
    node, path = found
    st = node.get_state_set()
    if not st.contains(S.SHOWING):
        Atspi.Component.scroll_to(node, Atspi.ScrollType.ANYWHERE)
    grabbed = not st.contains(S.FOCUSED)
    if grabbed:
        Atspi.Component.grab_focus(node)
    return {'name': node.get_name() or node.get_role_name(), 'path': list(path), 'grabbed': grabbed}


def input_path(pid: int | None, title: str, anchor_path: list | None, xid: int = 0) -> list | None:
    """Look the input box up ahead of time (no focus change), so the next fill finds it at once."""
    found = find_input(pid, title, anchor_path, xid=xid)
    return list(found[1]) if found else None
