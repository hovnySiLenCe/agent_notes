"""Spike: activate target app window, locate quote via AT-SPI, draw click-through overlay, screenshot."""
import os, sys, subprocess, time
os.environ.setdefault('QT_ENABLE_HIGHDPI_SCALING', '0')
import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi
from PySide6.QtCore import Qt, QTimer, QRect
from PySide6.QtGui import QPainter, QColor, QGuiApplication
from PySide6.QtWidgets import QApplication, QWidget
import x11util
T = Atspi.Text
pattern, quotes, shot = sys.argv[1], sys.argv[2].split('|'), sys.argv[3]
pids = {int(p) for p in subprocess.run(['pgrep', '-f', pattern], capture_output=True, text=True).stdout.split()}

def find_all(node, out):
    if 'Text' in (node.get_interfaces() or []) and node.get_role_name() != 'static':
        s = T.get_text(node, 0, T.get_character_count(node))
        for q in quotes:
            i = s.find(q)
            if i >= 0: out.append((node, i, i + len(q)))
    for k in range(node.get_child_count()):
        c = node.get_child_at_index(k)
        if c: find_all(c, out)

def rects(anchors):
    res = []
    for node, i, j in anchors:
        lines = {}
        for k in range(i, j):
            c = T.get_character_extents(node, k, Atspi.CoordType.SCREEN)
            if c.width <= 0: continue
            l = lines.setdefault(c.y, [c.x, c.y, c.x + c.width, c.y + c.height])
            l[0] = min(l[0], c.x); l[2] = max(l[2], c.x + c.width); l[3] = max(l[3], c.y + c.height)
        res += [QRect(a, b, c - a, e - b) for a, b, c, e in lines.values()]
    return res

class Overlay(QWidget):
    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowTransparentForInput | Qt.X11BypassWindowManagerHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setGeometry(QGuiApplication.primaryScreen().geometry())
        self.rs = []
    def paintEvent(self, e):
        p = QPainter(self)
        for r in self.rs:
            p.fillRect(r.adjusted(-2, 0, 2, 0), QColor(255, 200, 0, 90))
            p.fillRect(QRect(r.left() - 2, r.bottom() - 2, r.width() + 4, 4), QColor(255, 140, 0, 230))

app = QApplication(sys.argv)
wins = x11util.windows_for_pids(pids)
print('windows', wins)
x11util.activate(wins[0])
time.sleep(0.4)
desk = Atspi.get_desktop(0)
anchors = []
for a in (desk.get_child_at_index(i) for i in range(desk.get_child_count())):
    if a and a.get_process_id() in pids: find_all(a, anchors)
import overlay_spike_lib as L
vis = [a for a in anchors if L.visible(a[0], a[1])]
print('anchors', len(anchors), 'visible', len(vis))
ov = Overlay(); ov.rs = rects(vis); ov.show()
print('rects', [(r.x(), r.y(), r.width(), r.height()) for r in ov.rs])

def snap():
    u = ov.rs[0].united(ov.rs[-1]).adjusted(-500, -250, 500, 250)
    QGuiApplication.primaryScreen().grabWindow(0, u.x(), u.y(), u.width(), u.height()).save(shot)
    print('saved', shot); app.quit()
QTimer.singleShot(300, snap)
app.exec()
