"""Read the user's current text selection inside a window and turn it into a re-findable anchor."""
from __future__ import annotations

import time

from .geometry import display_cells
from .tree import OBJ, T, doc_url, frame_for, text_of, walk

CONTEXT_CHARS = 40


def _cell_to_char(text: str, offset: int) -> int:
    """VTE reports selection offsets as line-start char offset + *column*; wide (CJK) chars span 2 columns."""
    ls = text.rfind('\n', 0, max(0, min(offset, len(text)))) + 1
    col, i = offset - ls, ls
    while i < len(text) and text[i] != '\n' and col > 0:
        col -= display_cells(text[i])
        i += 1
    return i


def _fix_terminal(node, s: int, e: int, primary: str) -> tuple[int, int]:
    """Re-anchor a terminal selection on the exact PRIMARY text (nearest occurrence), else convert columns."""
    text = text_of(node)
    want = primary.strip('\n')
    if want:
        hits, i = [], text.find(want)
        while i >= 0:
            hits.append(i)
            i = text.find(want, i + 1)
        if hits:
            i = min(hits, key=lambda h: abs(h - s))
            return i, i + len(want)
    return _cell_to_char(text, s), _cell_to_char(text, e)


def capture_selection(pid: int | None, title: str, primary: str = '', budget: float = 1.5) -> dict | None:
    frame = frame_for(pid, title)
    if frame is None:
        return None
    hits = []
    for node, path, _ in walk(frame, time.monotonic() + budget):
        try:
            if T.get_n_selections(node) <= 0:
                continue
            sel = T.get_selection(node, 0)
        except Exception:
            continue          # not a Text object
        if sel.end_offset > sel.start_offset:
            s, e = sel.start_offset, sel.end_offset
            if node.get_role_name() == 'terminal':
                s, e = _fix_terminal(node, s, e, primary)
            hits.append((node, path, s, e))
    # Containers report the selection too (with embedded-object chars); keep only the deepest nodes.
    leaves = [h for h in hits
              if not any(len(o[1]) > len(h[1]) and o[1][:len(h[1])] == h[1] for o in hits)]
    parts = []
    for node, _, s, e in leaves:
        t = text_of(node, s, e).replace(OBJ, '')
        if t.strip():
            parts.append(t)
    if not parts:
        return None
    (fnode, fpath, fs, _), (lnode, lpath, _, le) = leaves[0], leaves[-1]
    return {
        'method': 'atspi',
        'quote': '\n'.join(parts),
        'prefix': text_of(fnode, fs - CONTEXT_CHARS, fs).replace(OBJ, ''),
        'suffix': text_of(lnode, le, le + CONTEXT_CHARS).replace(OBJ, ''),
        'path': list(fpath), 'start': fs,
        'end_path': list(lpath), 'end': le,
        'role': fnode.get_role_name(),
        'frame': frame.get_name() or '',
        'app': frame.get_application().get_name() if frame.get_application() else '',
        'url': doc_url(fnode),
    }
