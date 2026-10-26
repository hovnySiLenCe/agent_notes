"""Spike: (1) set a selection via AT-SPI, read X PRIMARY + selection offsets; (2) probe Shift+Alt+* grabs."""
import os, sys, time, subprocess, warnings
warnings.simplefilter('ignore')
import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi
from Xlib import X, XK, error
from PySide6.QtGui import QGuiApplication, QClipboard
from PySide6.QtWidgets import QApplication
import x11util as u, overlay_spike_lib as L

app = QApplication(sys.argv)
cb = QGuiApplication.clipboard()
saved_primary = cb.text(QClipboard.Selection)
for pat in ('ff-profile', 'vscode-ud'):
    pids = {int(p) for p in subprocess.run(['pgrep', '-f', pat], capture_output=True, text=True).stdout.split()}
    u.activate(u.windows_for_pids(pids)[0]); time.sleep(0.4)
    node, i, j = L.anchors(pids, ['防止梯度爆炸的技术'])[0]
    ok = Atspi.Text.set_selection(node, 0, i, j) if Atspi.Text.get_n_selections(node) else Atspi.Text.add_selection(node, i, j)
    t0 = time.time()
    while time.time() - t0 < 1.0: app.processEvents(); time.sleep(0.05)
    sel = Atspi.Text.get_selection(node, 0)
    print(pat, 'set', ok, '| PRIMARY =', repr(cb.text(QClipboard.Selection)[:30]),
          '| atspi selection offsets', (sel.start_offset, sel.end_offset), 'expected', (i, j))
    Atspi.Text.remove_selection(node, 0)

# hotkey grab probe
mods = X.ShiftMask | X.Mod1Mask
lock_variants = [0, X.LockMask, X.Mod2Mask, X.LockMask | X.Mod2Mask]   # CapsLock / NumLock
errs = []
def handler(err, *a): errs.append(err)
for k in ['a', 'e', 'r', 'q', 'space', 'Return', '1', '2', '3', 'h']:
    kc = u.d.keysym_to_keycode(XK.string_to_keysym(k))
    errs.clear()
    for lv in lock_variants:
        u.root.grab_key(kc, mods | lv, True, X.GrabModeAsync, X.GrabModeAsync, onerror=handler)
    u.d.sync()
    print('Shift+Alt+%-6s' % k, 'CONFLICT (already grabbed)' if errs else 'free')
    for lv in lock_variants:
        u.root.ungrab_key(kc, mods | lv)
    u.d.sync()
cb.setText(saved_primary, QClipboard.Selection)
