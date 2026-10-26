"""Spike: correct VTE (gnome-terminal) quote rects — VTE reports logical coords and ignores wide chars."""
import unicodedata
import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi
from PySide6.QtCore import QRect
import x11util as u
T, C = Atspi.Text, Atspi.CoordType


def cells(ch):
    return 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1


def vte_rects(term, xwin, i, j):
    """Screen rects (physical px) for chars [i, j) of a VTE terminal accessible inside X window xwin."""
    frame = term
    while frame.get_role_name() != 'frame':
        frame = frame.get_parent()
    fw = Atspi.Component.get_extents(frame, C.WINDOW).width
    o = u.d.create_resource_object('window', xwin)
    g, t = o.get_geometry(), o.translate_coords(u.root, 0, 0)
    scale = round(g.width / fw) if fw else 1
    s = T.get_text(term, 0, T.get_character_count(term))
    out = {}
    for k in range(i, j):
        if s[k] == '\n': continue
        ls = s.rfind('\n', 0, k) + 1                      # line start offset
        e0 = T.get_character_extents(term, ls, C.WINDOW)  # line start: x and row y are correct
        col = sum(cells(c) for c in s[ls:k])
        x = e0.x + col * e0.width  # line-start cell width == narrow cell width
        r = out.setdefault(e0.y, [x, e0.y, x, e0.y + e0.height])
        r[0] = min(r[0], x); r[2] = max(r[2], x + cells(s[k]) * e0.width)
    ox, oy = -t.x, -t.y
    return [QRect(ox + a * scale, oy + b * scale, (c - a) * scale, (d - b) * scale) for a, b, c, d in out.values()]
