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


_last: dict[tuple, tuple] = {}         # (pid, window title) -> path of the input box chosen last time


def _usable(node) -> bool:
    try:
        st = node.get_state_set()
        return st.contains(S.EDITABLE) and st.contains(S.FOCUSABLE) and 'Text' in (node.get_interfaces() or [])
    except Exception:
        return False


def find_input(pid: int | None, title: str, anchor_path: list | None, budget: float = 1.2):
    """Editable text boxes inside web content (never browser chrome such as the URL bar), ranked by:
    same document as the annotated text > looks like a chat box > already focused > lowest on screen.
    The box found last time in this window is tried first: walking the whole tree takes up to a second."""
    frame = frame_for(pid, title)
    if frame is None:
        return None
    from .locate import node_at
    cached = _last.get((pid, title))
    if cached is not None:
        node, _, doc = node_at(frame, cached)
        same_doc = not anchor_path or node_at(frame, anchor_path)[2] in ((), doc)
        if node is not None and same_doc and _usable(node):
            return node
    found = _search(frame, anchor_path, budget)
    if found is not None:
        _last[(pid, title)] = found[1]
        return found[0]
    return None


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


def focus_input(pid: int | None, title: str, anchor_path: list | None) -> str | None:
    node = find_input(pid, title, anchor_path)
    if node is None:
        return None
    st = node.get_state_set()
    if not st.contains(S.SHOWING):
        Atspi.Component.scroll_to(node, Atspi.ScrollType.ANYWHERE)
    if not st.contains(S.FOCUSED):
        Atspi.Component.grab_focus(node)
    return node.get_name() or node.get_role_name()
