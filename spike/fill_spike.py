"""Spike: find the target app's input box via AT-SPI, focus it, paste via clipboard + XTest, read back."""
import os, sys, subprocess, time
import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi
from Xlib import X, XK
from Xlib.ext import xtest
from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication, QClipboard
from PySide6.QtWidgets import QApplication
import x11util as u
S = Atspi.StateType
pattern, text = sys.argv[1], sys.argv[2]
paste_keys = sys.argv[3] if len(sys.argv) > 3 else 'ctrl+v'
pids = {int(p) for p in subprocess.run(['pgrep', '-f', pattern], capture_output=True, text=True).stdout.split()}

def inputs(n, out, in_doc=False):
    """Editable focusable text boxes inside web content (skips browser chrome like the URL bar)."""
    in_doc = in_doc or n.get_role_name() == 'document web'
    st = n.get_state_set()
    if in_doc and st.contains(S.EDITABLE) and st.contains(S.FOCUSABLE) \
            and 'Text' in (n.get_interfaces() or []):
        out.append(n); return
    for k in range(n.get_child_count()):
        c = n.get_child_at_index(k)
        if c: inputs(c, out, in_doc)

def read(n):
    return Atspi.Text.get_text(n, 0, Atspi.Text.get_character_count(n))

def key(combo):
    *mods, k = combo.split('+')
    codes = [u.d.keysym_to_keycode(XK.string_to_keysym({'ctrl': 'Control_L', 'shift': 'Shift_L'}[m])) for m in mods]
    codes.append(u.d.keysym_to_keycode(XK.string_to_keysym(k)))
    for c in codes: xtest.fake_input(u.d, X.KeyPress, c)
    for c in reversed(codes): xtest.fake_input(u.d, X.KeyRelease, c)
    u.d.sync()

app = QApplication(sys.argv)
cb = QGuiApplication.clipboard()
saved = cb.text(QClipboard.Clipboard)
desk = Atspi.get_desktop(0)
cands = []
for a in (desk.get_child_at_index(i) for i in range(desk.get_child_count())):
    if a and a.get_process_id() in pids: inputs(a, cands)
# heuristic: chat input = lowest editable box on screen
cands.sort(key=lambda n: Atspi.Component.get_extents(n, Atspi.CoordType.SCREEN).y)
print('inputs', [(n.get_role_name(), (n.get_name() or '')[:30]) for n in cands])
target = cands[-1] if cands else None

def go():
    u.activate(u.windows_for_pids(pids)[0])
    QTimer.singleShot(400, step2)
def step2():
    if target is not None:
        if not target.get_state_set().contains(S.SHOWING):
            print('scroll_to', Atspi.Component.scroll_to(target, Atspi.ScrollType.ANYWHERE))
        print('grab_focus', Atspi.Component.grab_focus(target))
    cb.setText(text, QClipboard.Clipboard)
    QTimer.singleShot(200, step3)
def step3():
    key(paste_keys)
    QTimer.singleShot(600, step4)
def step4():
    if target is not None:
        got = read(target)
        print('readback ok' if text.splitlines()[0] in got else 'readback MISMATCH', repr(got[:80]))
    cb.setText(saved, QClipboard.Clipboard)
    print('active', u.active_window(), 'clipboard restored')
    QTimer.singleShot(200, app.quit)
QTimer.singleShot(100, go)
app.exec()
