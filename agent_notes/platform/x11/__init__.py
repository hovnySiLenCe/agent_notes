"""Linux X11 platform: EWMH + XTest + XGrabKey, with AT-SPI for reading and focusing UI content."""
from __future__ import annotations

import os
import subprocess
import time

from ..base import Platform, WindowInfo
from . import keys, windows

TERMINAL_CLASSES = {
    'gnome-terminal-server', 'gnome-terminal', 'kgx', 'xterm', 'uxterm', 'kitty', 'alacritty', 'konsole',
    'terminator', 'tilix', 'xfce4-terminal', 'mate-terminal', 'lxterminal', 'qterminal', 'guake', 'tilda',
    'urxvt', 'rxvt', 'st', 'st-256color', 'foot', 'wezterm', 'org.wezfurlong.wezterm', 'terminology',
}


class X11Platform(Platform):
    def __init__(self, own_pid: int | None = None):
        self.own_pid = own_pid or os.getpid()
        self._tracker = None

    def _get_tracker(self):
        if self._tracker is None:
            from ..atspi.tracker import Tracker
            self._tracker = Tracker(self.own_pid)
        return self._tracker

    def track(self, reqs: list[dict], focus: set[str]) -> dict:
        return self._get_tracker().update(reqs, focus)

    def reveal(self, req: dict) -> bool:
        return self._get_tracker().reveal(req)

    def active_window(self) -> WindowInfo | None:
        return windows.active_window()

    def window_exists(self, xid: int) -> bool:
        return windows.exists(xid)

    def activate(self, xid: int) -> None:
        windows.activate(xid)

    def is_terminal(self, win: WindowInfo) -> bool:
        return win.wm_class.lower() in TERMINAL_CLASSES or win.wm_instance.lower() in TERMINAL_CLASSES

    def hotkey_listener(self):
        from .hotkeys import HotkeyListener
        return HotkeyListener()

    def selection_watcher(self):
        from .selwatch import SelectionWatcher
        return SelectionWatcher()

    def selection_belongs_to(self, win: WindowInfo) -> bool:
        return windows.primary_owned_by(win.xid)

    def capture_selection(self, win: WindowInfo, primary: str = '') -> dict | None:
        from ..atspi.capture import capture_selection
        return capture_selection(win.pid, win.title, primary)

    def inject(self, target: WindowInfo, terminal: bool, anchor_path: list | None, auto_send: bool) -> dict:
        keys.wait_modifiers_released()
        windows.activate(target.xid)
        if not windows.wait_active(target.xid, 1.2):
            return {'ok': False, 'reason': 'activate'}
        focused = None
        if not terminal:
            try:
                from ..atspi.inputs import focus_input
                focused = focus_input(target.pid, target.title, anchor_path)
            except Exception:
                focused = None
            time.sleep(0.15)
        if windows.active_xid() != target.xid:          # never type into a window the user switched to
            return {'ok': False, 'reason': 'focus_lost'}
        if terminal:
            keys.send('shift+Insert')                   # VTE & co. paste PRIMARY here; the caller set both
        else:
            if focused:
                keys.send('ctrl+End')                   # append after any draft the user already typed
            keys.send('ctrl+v')
        if auto_send:
            time.sleep(0.35)
            keys.send('Return')
        return {'ok': True, 'input': focused}

    def anchor_from_text(self, win: WindowInfo, quote: str) -> dict | None:
        from ..atspi.locate import anchor_from_text
        return anchor_from_text(win.pid, win.xid, quote)

    def app_accessible(self, win: WindowInfo) -> bool:
        from ..atspi.locate import app_accessible
        return app_accessible(win.pid)

    def warm_up(self) -> None:
        from ..atspi.tree import Atspi
        desk = Atspi.get_desktop(0)
        for i in range(desk.get_child_count()):
            a = desk.get_child_at_index(i)
            if a is not None:
                a.get_process_id()
        windows.active_window()

    def compositing(self) -> bool:
        return windows.compositing()

    def accessibility_enabled(self) -> bool:
        try:
            out = subprocess.run(['gsettings', 'get', 'org.gnome.desktop.interface', 'toolkit-accessibility'],
                                 capture_output=True, text=True, timeout=2).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            return True     # not GNOME / no gsettings: don't nag
        return out == 'true'
