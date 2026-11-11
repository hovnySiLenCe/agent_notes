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


def find_input(pid: int | None, title: str, anchor_path: list | None, budget: float = 1.2):
    """Editable text boxes inside web content (never browser chrome such as the URL bar), ranked by:
    same document as the annotated text > looks like a chat box > already focused > lowest on screen."""
    frame = frame_for(pid, title)
    if frame is None:
        return None
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
                best, best_score = node, score
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
