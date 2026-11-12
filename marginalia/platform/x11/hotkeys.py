"""Global hotkeys via XGrabKey on the root window, listened to on a dedicated thread."""
from __future__ import annotations

import logging
import select
import threading
import time

from PySide6.QtCore import QObject, Signal
from Xlib import X, XK, display, error
from Xlib.ext import xtest

log = logging.getLogger(__name__)

MASKS = {'shift': X.ShiftMask, 'ctrl': X.ControlMask, 'control': X.ControlMask,
         'alt': X.Mod1Mask, 'super': X.Mod4Mask, 'win': X.Mod4Mask}
_RELEVANT = X.ShiftMask | X.ControlMask | X.Mod1Mask | X.Mod4Mask
_LOCK_VARIANTS = (0, X.LockMask, X.Mod2Mask, X.LockMask | X.Mod2Mask)   # CapsLock / NumLock on or off
_KEY_ALIASES = {'space': 'space', 'enter': 'Return', 'return': 'Return', 'esc': 'Escape', 'escape': 'Escape',
                'tab': 'Tab', 'backspace': 'BackSpace', 'del': 'Delete', 'delete': 'Delete', 'insert': 'Insert',
                'up': 'Up', 'down': 'Down', 'left': 'Left', 'right': 'Right'}
_REPEAT_GUARD = 0.5   # seconds; swallows key autorepeat while the combo is held


def parse(spec: str) -> tuple[int, int]:
    """'Shift+Alt+Space' -> (modifier mask, keysym)."""
    parts = [p.strip() for p in spec.split('+') if p.strip()]
    if not parts:
        raise ValueError('空的快捷键')
    *mods, key = parts
    mask = 0
    for m in mods:
        if m.lower() not in MASKS:
            raise ValueError(f'未知修饰键: {m}')
        mask |= MASKS[m.lower()]
    name = _KEY_ALIASES.get(key.lower(), key.lower() if len(key) == 1 else key)
    keysym = XK.string_to_keysym(name)
    if not keysym:
        raise ValueError(f'未知按键: {key}')
    return mask, keysym


class HotkeyListener(QObject):
    triggered = Signal(str)        # action
    failed = Signal(str, str)      # spec, reason

    def __init__(self):
        super().__init__()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self, bindings: dict[str, str]) -> None:
        self.stop()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(dict(bindings), self._stop),
                                        name='marginalia-hotkeys', daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread:
            self._stop.set()
            self._thread.join(timeout=2)
            self._thread = None

    def _run(self, bindings: dict[str, str], stop: threading.Event) -> None:
        d = display.Display()
        root = d.screen().root
        grabbed: dict[tuple[int, int], str] = {}
        for action, spec in bindings.items():
            try:
                mask, keysym = parse(spec)
            except ValueError as e:
                self.failed.emit(spec, str(e))
                continue
            kc = d.keysym_to_keycode(keysym)
            if not kc:
                self.failed.emit(spec, '当前键盘布局中没有这个键')
                continue
            if (kc, mask) in grabbed:
                self.failed.emit(spec, f'与 {grabbed[(kc, mask)]} 重复')
                continue
            catch = error.CatchError(error.BadAccess)
            for lv in _LOCK_VARIANTS:
                root.grab_key(kc, mask | lv, True, X.GrabModeAsync, X.GrabModeAsync, onerror=catch)
            d.sync()
            if catch.get_error():
                for lv in _LOCK_VARIANTS:
                    root.ungrab_key(kc, mask | lv)
                self.failed.emit(spec, '已被其他程序占用')
                continue
            grabbed[(kc, mask)] = action
        log.info('hotkeys grabbed: %s', {v: k for k, v in grabbed.items()})

        last: dict[str, float] = {}
        grabbed_codes = {kc for kc, _ in grabbed}
        ctrl = d.keysym_to_keycode(XK.string_to_keysym('Control_L'))
        try:
            while not stop.is_set():
                select.select([d], [], [], 0.2)
                while d.pending_events():
                    ev = d.next_event()
                    if ev.type == X.KeyRelease and ev.detail in grabbed_codes and ev.state & X.Mod1Mask and ctrl:
                        # Our key is up, Alt still down: the app saw Alt go down but not our key, so releasing
                        # Alt now would look like a lone Alt tap, which moves the focus to the menu bar (VS Code,
                        # Firefox …) and the paste that follows lands there. A Ctrl tap in between breaks it.
                        xtest.fake_input(d, X.KeyPress, ctrl)
                        xtest.fake_input(d, X.KeyRelease, ctrl)
                        d.sync()
                        log.info('hotkey released before Alt: tapped Ctrl so the app does not open its menu bar')
                        continue
                    if ev.type != X.KeyPress:
                        continue
                    action = grabbed.get((ev.detail, ev.state & _RELEVANT))
                    if action is None:
                        continue
                    now = time.monotonic()
                    held = now - last.get(action, 0.0) < _REPEAT_GUARD
                    last[action] = now
                    if not held:
                        self.triggered.emit(action)
        finally:
            for kc, mask in grabbed:
                for lv in _LOCK_VARIANTS:
                    root.ungrab_key(kc, mask | lv)
            d.sync()
            d.close()
