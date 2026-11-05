"""Highlights on the original text: which annotations to show, polling their positions, clipping, jumping back.

Runs on the Qt main thread; all accessibility / X queries go through the worker (platform.track / reveal).
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRect, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QRegion

from .core.models import PENDING, RESOLVED, Annotation
from .ui.overlay import HighlightOverlay, Mark

if TYPE_CHECKING:
    from .app import Controller

log = logging.getLogger(__name__)

FAST_MS = 33           # while things are moving (scrolling): ~30 fps; a tick that moved costs ~20 ms
SLOW_MS = 150          # while nothing changes (a tick that finds nothing moved costs ~1 ms)
MOVING_S = 1.2         # keep polling fast this long after the last movement / wheel turn
IDLE_MS = 1000         # nothing to track
FLASH_S = 2.5          # how long a jumped-to annotation stays emphasized
SHOW_MODES = ('pending', 'all', 'hover')


def _qrect(r) -> QRect:
    return QRect(int(r[0]), int(r[1]), int(r[2]), int(r[3]))


class Highlighter(QObject):
    states_changed = Signal()           # per-annotation locate states changed (cards show them)

    def __init__(self, ctl: 'Controller', overlay: HighlightOverlay | None = None):
        super().__init__()
        self.ctl = ctl
        self.overlay = overlay or HighlightOverlay()
        self.hover_id: str | None = None
        self._flash: dict[str, float] = {}       # ann id -> monotonic deadline
        self.states: dict[str, str] = {}         # ann id -> ok | offscreen | missing | hidden
        self._inflight = False
        self._moving_until = 0.0
        self._last_marks: tuple = ()
        self._timer = QTimer(self, singleShot=True, timeout=self.tick)
        self._timer.start(SLOW_MS)
        comp = getattr(ctl.platform, 'compositing', None)
        if comp is not None:
            ctl.worker.submit(comp, cb=lambda on: setattr(self.overlay, 'translucent', on is not False))

    # ---- settings -----------------------------------------------------------------------------------------
    @property
    def settings(self) -> dict:
        return self.ctl.cfg.data.get('highlight', {})

    def enabled(self) -> bool:
        return bool(self.settings.get('enabled', True)) and self.ctl.state.get('highlight_on', True)

    def set_enabled(self, on: bool) -> None:
        self.ctl.state['highlight_on'] = on
        self.ctl.save_state()
        if not on:
            self.overlay.set_marks([])
        sync = getattr(self.ctl, '_sync_watcher', None)      # the wheel listener runs only when someone needs it
        if sync:
            sync()
        self.poke()

    def show_mode(self) -> str:
        m = self.settings.get('show', 'pending')
        return m if m in SHOW_MODES else 'pending'

    # ---- interaction ----------------------------------------------------------------------------------------
    def set_hover(self, ann_id: str | None) -> None:
        if ann_id != self.hover_id:
            self.hover_id = ann_id
            self.poke()

    def flash(self, ann_id: str) -> None:
        self._flash[ann_id] = time.monotonic() + FLASH_S
        self.poke()

    def poke(self) -> None:
        """Re-measure soon (after a hover change, a jump, a store change …)."""
        self._timer.start(0)

    def scrolled(self) -> None:
        """The mouse wheel turned somewhere: content is about to move, track it closely from now on."""
        self._moving_until = time.monotonic() + MOVING_S
        if not self._inflight:
            self._timer.start(0)

    def focus_ids(self) -> set[str]:
        now = time.monotonic()
        self._flash = {k: v for k, v in self._flash.items() if v > now}
        return set(self._flash) | ({self.hover_id} if self.hover_id else set())

    @staticmethod
    def request(a: Annotation) -> dict | None:
        xid = a.source.get('xid')
        if not xid or a.anchor.get('method') != 'atspi':
            return None
        return {'id': a.id, 'xid': xid, 'pid': a.source.get('pid'), 'anchor': a.anchor, 'quote': a.quote}

    def candidates(self) -> list[Annotation]:
        focus, mode = self.focus_ids(), self.show_mode()
        out = []
        for a in self.ctl.store.all():
            if a.id in focus or (mode == 'all' and a.status != RESOLVED) or (mode == 'pending' and a.status == PENDING):
                out.append(a)
        return out

    # ---- polling --------------------------------------------------------------------------------------------
    def tick(self) -> None:
        if self._inflight:
            return
        if not self.enabled():
            self.overlay.set_marks([])
            self._timer.start(IDLE_MS)
            return
        if getattr(self.ctl, '_busy', False):          # capture / fill in progress: stay out of the way
            self._timer.start(SLOW_MS)
            return
        reqs = [r for r in (self.request(a) for a in self.candidates()) if r]
        if not reqs:
            self.apply({'context': None, 'items': {}, 'windows': {}})
            self._timer.start(IDLE_MS)
            return
        self._inflight = True
        self.ctl.worker.submit(self.ctl.platform.track, reqs, self.focus_ids(), cb=self._on_tracked)

    def _on_tracked(self, res) -> None:
        self._inflight = False
        if isinstance(res, Exception) or not isinstance(res, dict):
            self._timer.start(IDLE_MS)
            return
        now = time.monotonic()
        if self.apply(res):
            self._moving_until = now + MOVING_S
        self._timer.start(FAST_MS if now < self._moving_until or self.focus_ids() else SLOW_MS)

    # ---- painting -------------------------------------------------------------------------------------------
    def _own_windows(self) -> QRegion:
        """Our own visible windows (panel, popup, toast) in physical pixels: never paint over them."""
        dpr = self._dpr()
        reg = QRegion()
        for w in (getattr(self.ctl, 'panel', None), getattr(self.ctl, 'popup', None), getattr(self.ctl, 'toast', None)):
            if w is not None and w.isVisible():
                g = w.frameGeometry()
                reg = reg.united(QRegion(QRect(round(g.x() * dpr), round(g.y() * dpr),
                                               round(g.width() * dpr), round(g.height() * dpr))))
        return reg

    @staticmethod
    def _dpr() -> float:
        scr = QGuiApplication.primaryScreen()
        return scr.devicePixelRatio() if scr else 1.0

    def apply(self, res: dict) -> bool:
        """Turn a tracker result into overlay marks. Returns True when the picture changed."""
        types = self.ctl.cfg.type_map
        focus = self.focus_ids()
        mode = self.show_mode()
        own = self._own_windows()
        dpr = self._dpr()
        by_id = {a.id: a for a in self.ctl.store.all()}
        marks = []
        states = dict(self.states)
        for ann_id, item in res.get('items', {}).items():
            states[ann_id] = item.get('state', '')
            a = by_id.get(ann_id)
            if a is None or not item.get('rects'):
                continue
            if ann_id not in focus and (mode == 'hover' or a.source.get('xid') != res.get('context')):
                continue
            win = res.get('windows', {}).get(a.source.get('xid'), {})
            region = QRegion()
            for r in item['rects']:
                region = region.united(QRegion(_qrect(r)))
            if win.get('rect'):
                region = region.intersected(QRegion(_qrect(win['rect'])))
            for occ in win.get('occluders', []):
                region = region.subtracted(QRegion(_qrect(occ)))
            region = region.subtracted(own)
            rects = tuple(QRect(round(r.x() / dpr), round(r.y() / dpr), max(1, round(r.width() / dpr)),
                                max(1, round(r.height() / dpr))) for r in region)
            if rects:
                color = types[a.type_id].color if a.type_id in types else '#7C8594'
                marks.append(Mark(rects, color, ann_id in focus))
        marks.sort(key=lambda m: (m.focus, m.color))
        if states != self.states:
            self.states = states
            self.states_changed.emit()
        changed = tuple(marks) != self._last_marks
        self._last_marks = tuple(marks)
        self.overlay.set_marks(marks)
        return changed

    # ---- jump back to the original text ---------------------------------------------------------------------
    def jump(self, a: Annotation) -> None:
        req = self.request(a)
        xid = a.source.get('xid')
        if not xid or not self.ctl.platform.window_exists(xid):
            self.ctl.toast.show_message('来源窗口已关闭', 'warn', near=self.ctl.panel)
            return
        self.ctl.worker.submit(self.ctl.platform.activate, xid)
        if req is None:            # captured without an anchor: switching to the window is all we can do
            return

        def done(ok) -> None:
            if ok is True:
                self.flash(a.id)
            else:
                self.ctl.toast.show_message('未在原窗口中找到这段原文（可能已关闭页面或内容已变）', 'warn', 2600,
                                            near=self.ctl.panel)
        self.ctl.worker.submit(self.ctl.platform.reveal, req, cb=done)
