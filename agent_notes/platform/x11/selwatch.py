"""Notice when the user selects text with the mouse anywhere on the desktop (for the selection bubble).

XFixes reports every change of the PRIMARY selection's owner; XInput2 raw events report every mouse button
press/release without grabbing anything. A selection gesture = the left button is released and PRIMARY was set
at or after the moment it went down (apps set PRIMARY either while dragging or on release, hence the short wait).
Keyboard selections and programmatic changes are ignored. Wheel turns (buttons 4-7) are reported too, so the
highlights can start following a scroll at once. Listened to on a dedicated thread with its own
X connection.
"""
from __future__ import annotations

import logging
import select
import struct
import threading
import time

from PySide6.QtCore import QObject, Signal
from Xlib import Xatom, display
from Xlib.ext import xfixes, xinput

log = logging.getLogger(__name__)

SETTLE = 0.15        # seconds after release before deciding (apps that set PRIMARY on mouse-up)
WHEEL_GAP = 0.05     # at most one `scrolled` per this many seconds


class SelectionWatcher(QObject):
    selected = Signal()          # a mouse gesture just selected text (in whatever window is active)
    pressed = Signal()           # a mouse button went down somewhere (hide transient UI)
    scrolled = Signal()          # the mouse wheel turned somewhere

    def __init__(self):
        super().__init__()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread:
            return
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(self._stop,), name='agent-notes-selection',
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread:
            self._stop.set()
            self._thread.join(timeout=2)
            self._thread = None

    @property
    def running(self) -> bool:
        return self._thread is not None

    def _run(self, stop: threading.Event) -> None:
        try:
            d = display.Display()
        except Exception as e:
            log.warning('selection watcher: no display: %s', e)
            return
        root = d.screen().root
        if not (d.has_extension('XFIXES') and d.has_extension('XInputExtension')):
            log.warning('selection watcher: XFIXES / XInput2 missing; no selection bubble')
            d.close()
            return
        d.xfixes_query_version()
        xi = d.query_extension('XInputExtension').major_opcode
        d.xfixes_select_selection_input(root, Xatom.PRIMARY, xfixes.XFixesSetSelectionOwnerNotifyMask)
        root.xinput_select_events([(xinput.AllMasterDevices, xinput.RawButtonPressMask | xinput.RawButtonReleaseMask)])
        d.sync()
        down_at = 0          # server time the left button went down
        owned_at = -1        # server time PRIMARY last got an owner
        check_at = None      # monotonic deadline for the pending decision
        wheel_at = 0.0
        try:
            while not stop.is_set():
                wait = 0.2 if check_at is None else max(0.0, min(0.2, check_at - time.monotonic()))
                select.select([d], [], [], wait)
                while d.pending_events():
                    ev = d.next_event()
                    if hasattr(ev, 'selection_timestamp'):          # XFixes SetSelectionOwnerNotify
                        if getattr(ev.owner, 'id', ev.owner):      # 0 = selection cleared
                            owned_at = max(ev.selection_timestamp, ev.timestamp)
                        continue
                    if getattr(ev, 'extension', None) != xi or getattr(ev, 'evtype', None) not in (
                            xinput.RawButtonPress, xinput.RawButtonRelease) or len(ev.data) < 10:
                        continue
                    _, t, button = struct.unpack_from('<HII', ev.data)
                    if ev.evtype == xinput.RawButtonPress:
                        if button in (1, 2, 3):
                            self.pressed.emit()
                        elif button in (4, 5, 6, 7) and time.monotonic() - wheel_at > WHEEL_GAP:
                            wheel_at = time.monotonic()
                            self.scrolled.emit()
                        if button == 1:
                            down_at, check_at = t, None
                    elif button == 1 and down_at:
                        check_at = time.monotonic() + SETTLE
                if check_at is not None and time.monotonic() >= check_at:
                    check_at = None
                    if owned_at >= down_at:
                        self.selected.emit()
        except Exception:
            log.exception('selection watcher stopped')
        finally:
            d.close()
