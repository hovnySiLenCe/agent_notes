"""Spike lib: AT-SPI quote locate -> per-line screen rects."""
import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi
from PySide6.QtCore import QRect
T = Atspi.Text

def _find_all(node, quotes, out):
    if 'Text' in (node.get_interfaces() or []) and node.get_role_name() != 'static':
        s = T.get_text(node, 0, T.get_character_count(node))
        for q in quotes:
            i = s.find(q)
            if i >= 0: out.append((node, i, i + len(q)))
    for k in range(node.get_child_count()):
        c = node.get_child_at_index(k)
        if c: _find_all(c, quotes, out)

def anchors(pids, quotes):
    desk = Atspi.get_desktop(0); out = []
    for a in (desk.get_child_at_index(i) for i in range(desk.get_child_count())):
        if a and a.get_process_id() in pids: _find_all(a, quotes, out)
    return out

def rects(anchs):
    res = []
    for node, i, j in anchs:
        lines = {}
        for k in range(i, j):
            c = T.get_character_extents(node, k, Atspi.CoordType.SCREEN)
            if c.width <= 0: continue
            l = lines.setdefault(c.y, [c.x, c.y, c.x + c.width, c.y + c.height])
            l[0] = min(l[0], c.x); l[2] = max(l[2], c.x + c.width); l[3] = max(l[3], c.y + c.height)
        res += [QRect(a, b, c - a, e - b) for a, b, c, e in lines.values()]
    return res

def locate(pids, quotes):
    return rects(anchors(pids, quotes))

def _hit(app, x, y):
    """Deepest accessible at screen point, descending from each top-level frame."""
    for k in range(app.get_child_count()):
        n, best = app.get_child_at_index(k), None
        while n is not None and n != best:
            best = n
            try:
                n = Atspi.Component.get_accessible_at_point(n, x, y, Atspi.CoordType.SCREEN)
            except Exception:
                n = None
        if best is not None and best != app.get_child_at_index(k):
            return best
    return None

def _contains(anc, n):
    while n is not None:
        if n == anc: return True
        n = n.get_parent()
    return False

def visible(node, i):
    """True if the char at offset i is the topmost thing at its point inside its own app."""
    c = T.get_character_extents(node, i, Atspi.CoordType.SCREEN)
    # Chromium only hit-tests reliably from inside web content: start at the outermost
    # 'document web' ancestor (covers in-app dialogs); fall back to the top-level frame.
    root, n = None, node
    while n is not None:
        r = n.get_role_name()
        if r == 'document web' or (root is None and r == 'frame'):
            root = n
        n = n.get_parent()
    h = Atspi.Component.get_accessible_at_point(root, c.x + c.width // 2, c.y + c.height // 2,
                                                Atspi.CoordType.SCREEN)
    return _contains(node, h)
