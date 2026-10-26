"""Spike: CLI case — locate quote in a gnome-terminal via AT-SPI, overlay screenshot, paste with ctrl+shift+v."""
import os, sys, time, warnings
warnings.simplefilter('ignore')
os.environ.setdefault('QT_ENABLE_HIGHDPI_SCALING', '0')
import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi
from Xlib import X, XK
from Xlib.ext import xtest
from PySide6.QtCore import Qt, QTimer, QRect
from PySide6.QtGui import QGuiApplication, QClipboard, QPainter, QColor
from PySide6.QtWidgets import QApplication, QWidget
import x11util as u, overlay_spike_lib as L

MARK, QUOTE, shot, out_file = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
PASTE = '请根据以下批注调整你上一条回复：\n1.【追问】「' + QUOTE + '」→ 为什么不用权重衰减？'


def key(combo):
    *mods, k = combo.split('+')
    names = {'ctrl': 'Control_L', 'shift': 'Shift_L'}
    codes = [u.d.keysym_to_keycode(XK.string_to_keysym(names[m])) for m in mods]
    codes.append(u.d.keysym_to_keycode(XK.string_to_keysym(k)))
    for c in codes: xtest.fake_input(u.d, X.KeyPress, c)
    for c in reversed(codes): xtest.fake_input(u.d, X.KeyRelease, c)
    u.d.sync()


def find_window(title):
    for w in u.client_windows():
        n = u.d.create_resource_object('window', w).get_full_property(u.A('_NET_WM_NAME'), 0)
        if n and title in n.value.decode(errors='ignore'):
            return w


def find_terminal_node():
    desk = Atspi.get_desktop(0)
    hits = []
    def walk(n, in_win=False):
        # match the window by its AT-SPI frame title, never by content (other terminals may echo MARK)
        in_win = in_win or (n.get_role_name() == 'frame' and MARK in (n.get_name() or ''))
        if n.get_role_name() == 'terminal':
            if in_win and n.get_state_set().contains(Atspi.StateType.SHOWING):
                hits.append((n, Atspi.Text.get_text(n, 0, Atspi.Text.get_character_count(n))))
            return
        for k in range(n.get_child_count()):
            c = n.get_child_at_index(k)
            if c: walk(c, in_win)
    for a in (desk.get_child_at_index(i) for i in range(desk.get_child_count())):
        if a and a.get_name() == 'gnome-terminal-server': walk(a)
    return hits[0] if hits else (None, '')


class Overlay(QWidget):
    def __init__(self, rs):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowTransparentForInput | Qt.X11BypassWindowManagerHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setGeometry(QGuiApplication.primaryScreen().geometry())
        self.rs = rs
    def paintEvent(self, e):
        p = QPainter(self)
        for r in self.rs:
            p.fillRect(r.adjusted(-2, 0, 2, 0), QColor(80, 160, 255, 90))
            p.fillRect(QRect(r.left() - 2, r.bottom() - 2, r.width() + 4, 4), QColor(40, 120, 255, 230))


app = QApplication(sys.argv)
cb = QGuiApplication.clipboard()
saved = cb.text(QClipboard.Clipboard)
saved_primary = cb.text(QClipboard.Selection)
win = find_window(MARK)
print('terminal window', win)
u.activate(win)
time.sleep(0.5)
node, text = find_terminal_node()
i = text.find(QUOTE)
print('terminal text found', node is not None, 'quote offset', i)
rs = L.rects([(node, i, i + len(QUOTE))]) if i >= 0 else []
print('rects', [(r.x(), r.y(), r.width(), r.height()) for r in rs])
ov = Overlay(rs); ov.show()


def snap():
    if rs:
        g = rs[0].adjusted(-600, -200, 600, 200)
        QGuiApplication.primaryScreen().grabWindow(0, g.x(), g.y(), g.width(), g.height()).save(shot)
        print('saved', shot)
    ov.hide()
    cb.setText(PASTE, QClipboard.Clipboard)
    cb.setText(PASTE, QClipboard.Selection)  # terminals paste PRIMARY on shift+Insert
    QTimer.singleShot(200, paste)


def paste():
    print('clipboard owner has text', cb.text(QClipboard.Clipboard)[:20])
    key(sys.argv[5] if len(sys.argv) > 5 else 'ctrl+shift+v')
    QTimer.singleShot(800, check)


def check():
    n, s = find_terminal_node()
    print('terminal shows paste', PASTE.splitlines()[1][:12] in s, repr(s.strip()[-80:]))
    QTimer.singleShot(100, finish)


def finish():
    key('Return'); time.sleep(0.2); key('ctrl+d')
    cb.setText(saved, QClipboard.Clipboard)
    cb.setText(saved_primary, QClipboard.Selection)
    QTimer.singleShot(800, verify)


def verify():
    got = open(out_file).read() if os.path.exists(out_file) else ''
    print('file ok' if got.strip() == PASTE else 'file MISMATCH', repr(got[:120]))
    app.quit()


QTimer.singleShot(400, snap)
app.exec()
