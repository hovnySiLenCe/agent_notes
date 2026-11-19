"""Sandbox check of keys.wait_keys_released with a "physical" keyboard: the Xvfb keyboard device, driven through
XTestFakeDeviceKeyEvent, so the keys come from a real slave device and not from the XTEST one our code uses.

    .venv/bin/python -m tests.e2e.sandbox -- .venv/bin/python -m tests.e2e.check_keys
"""
from __future__ import annotations

import ctypes
import subprocess
import sys
import threading
import time

from Xlib import X, XK, display

from marginalia.platform.x11 import keys

results: list[tuple[str, bool]] = []


def check(name: str, ok: bool, detail: str = '') -> None:
    results.append((name, ok))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f'  — {detail}' if detail and not ok else ''), flush=True)


class Physical:
    """Key presses from the Xvfb keyboard device."""

    def __init__(self):
        out = subprocess.run(['xinput', 'list', '--short'], capture_output=True, text=True).stdout
        line = next(ln for ln in out.splitlines() if 'Xvfb keyboard' in ln)
        dev_id = int(line.split('id=')[1].split()[0])
        self.x = ctypes.CDLL('libX11.so.6')
        xi, self.xt = ctypes.CDLL('libXi.so.6'), ctypes.CDLL('libXtst.so.6')
        self.x.XOpenDisplay.restype = ctypes.c_void_p
        self.x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.x.XFlush.argtypes = [ctypes.c_void_p]
        xi.XOpenDevice.restype = ctypes.c_void_p
        xi.XOpenDevice.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self.xt.XTestFakeDeviceKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_int,
                                                    ctypes.POINTER(ctypes.c_int), ctypes.c_int, ctypes.c_ulong]
        self.dpy = self.x.XOpenDisplay(None)
        self.dev = xi.XOpenDevice(self.dpy, dev_id)
        if not self.dev:
            raise SystemExit('cannot open the Xvfb keyboard device')

    def key(self, code: int, down: bool) -> None:
        self.xt.XTestFakeDeviceKeyEvent(self.dpy, self.dev, code, int(down), None, 0, 0)
        self.x.XFlush(self.dpy)
        time.sleep(0.02)


def main() -> int:
    d = display.Display()
    kc = lambda name: d.keysym_to_keycode(XK.string_to_keysym(name))      # noqa: E731
    shift, alt, ret, sup, v = kc('Shift_L'), kc('Alt_L'), kc('Return'), kc('Super_L'), kc('v')
    phys = Physical()
    s = d.screen()
    w = s.root.create_window(0, 0, 200, 200, 0, s.root_depth, event_mask=X.KeyPressMask | X.KeyReleaseMask)
    w.map()
    d.sync()
    time.sleep(0.2)
    w.set_input_focus(X.RevertToParent, X.CurrentTime)
    d.sync()

    def events() -> list[tuple[str, int, int]]:
        time.sleep(0.05)
        out = []
        while d.pending_events():
            e = d.next_event()
            if e.type in (X.KeyPress, X.KeyRelease):
                out.append(('press' if e.type == X.KeyPress else 'release', e.detail, e.state))
        return out

    # Shift+Alt+Return: Return comes up after 120 ms, the modifiers much later.
    for c in (shift, alt, ret):
        phys.key(c, True)
    events()
    threading.Timer(0.12, lambda: phys.key(ret, False)).start()
    t = time.monotonic()
    ok = keys.wait_keys_released()
    took = time.monotonic() - t
    check('returns once Return is up, modifiers still held', ok and 0.1 < took < 0.3, f'{ok} after {took:.3f}s')
    keys.send('ctrl+v')
    got = events()
    paste = [e for e in got if e[0] == 'press' and e[1] == v]
    check('the paste carries Ctrl only', paste and paste[0][2] == X.ControlMask, str(got))
    check('Alt was not released on its own (Ctrl tapped first)',
          any(e[1] == kc('Control_L') for e in got[:2]), str(got))
    phys.key(shift, False)
    phys.key(alt, False)
    check('the real release later is not delivered again', events() == [], 'events after the physical release')

    # Super held: waited for, not released for the user.
    phys.key(sup, True)
    t = time.monotonic()
    ok = keys.wait_keys_released(timeout=0.3)
    check('Super is waited for', not ok and time.monotonic() - t >= 0.3)
    threading.Timer(0.1, lambda: phys.key(sup, False)).start()
    check('…until it is up', keys.wait_keys_released(timeout=1.0))
    events()

    failed = [n for n, ok in results if not ok]
    print(f'\n{len(results) - len(failed)}/{len(results)} checks passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
