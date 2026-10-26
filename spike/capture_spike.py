"""Spike: capture an (obscured) window via XComposite and draw AT-SPI rects onto it."""
import os, sys, subprocess
import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi
from Xlib import X
from Xlib.ext import composite
from PySide6.QtGui import QImage, QPainter, QColor, QGuiApplication
import x11util as u
import overlay_spike_lib as L

pattern, quotes, out = sys.argv[1], sys.argv[2].split('|'), sys.argv[3]
pids = {int(p) for p in subprocess.run(['pgrep', '-f', pattern], capture_output=True, text=True).stdout.split()}
wid = u.windows_for_pids(pids)[0]
w = u.d.create_resource_object('window', wid)
frame = w
while True:
    t = frame.query_tree()
    if t.parent == u.root: break
    frame = t.parent
g = frame.get_geometry()
pm = frame.composite_name_window_pixmap()
img = pm.get_image(0, 0, g.width, g.height, X.ZPixmap, 0xffffffff)
qi = QImage(img.data, g.width, g.height, QImage.Format_RGB32).copy()
origin = frame.translate_coords(u.root, 0, 0)
ox, oy = -origin.x, -origin.y
rects = L.locate(pids, quotes)
p = QPainter(qi)
for r in rects:
    r = r.translated(-ox, -oy)
    p.fillRect(r.adjusted(-2, 0, 2, 0), QColor(255, 200, 0, 90))
    p.fillRect(r.left() - 2, r.bottom() - 2, r.width() + 4, 4, QColor(255, 140, 0, 230))
p.end()
qi.save(out)
print('frame', (ox, oy, g.width, g.height), 'rects', [(r.x(), r.y(), r.width(), r.height()) for r in rects], 'saved', out)
