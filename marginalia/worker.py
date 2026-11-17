"""Single background thread for blocking platform calls (AT-SPI D-Bus, X round-trips).

Calls to the platform's own methods (`worker.submit(platform.track, ...)`) are forwarded to the helper process
(helper.py), so a native crash in an accessibility query can't take the app down. Results are delivered back on
the Qt main thread through a queued signal.
"""
from __future__ import annotations

import itertools
import logging
import queue
import threading
import time
from typing import Callable

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)
SLOW_WAIT = 0.05      # s; an urgent call that had to wait longer than this for the worker is logged


class Worker(QObject):
    """One thread, so the helper sees one call at a time; urgent calls (the user is waiting: fill, capture,
    switching windows) are taken before queued background ones (highlight tracking, late anchors)."""
    _done = Signal(object, object)   # callback, result (or exception)

    def __init__(self, remote: object | None = None, helper=None):
        """remote: the object whose bound methods run in `helper` (a helper.Helper) instead of this process."""
        super().__init__()
        self._q: queue.PriorityQueue = queue.PriorityQueue()
        self._seq = itertools.count()
        self._closed = False
        self._remote, self._helper = remote, helper
        self._done.connect(self._dispatch)
        self._thread = threading.Thread(target=self._loop, name='marginalia-worker', daemon=True)
        self._thread.start()

    def submit(self, fn: Callable, *args, cb: Callable | None = None, urgent: bool = False) -> None:
        if self._closed:             # shutting down: timers may still fire once
            return
        self._q.put((0 if urgent else 1, next(self._seq), time.monotonic(), fn, args, cb))

    def pending(self) -> int:
        return self._q.qsize()

    def _loop(self) -> None:
        while True:
            prio, _, queued, fn, args, cb = self._q.get()
            if fn is None:
                return
            name = getattr(fn, '__name__', str(fn))
            waited = time.monotonic() - queued
            if prio == 0 and waited > SLOW_WAIT:
                log.info('%s waited %.0f ms for the worker', name, waited * 1000)
            remote = self._helper is not None and getattr(fn, '__self__', None) is self._remote
            try:
                result = self._helper.call(name, *args) if remote else fn(*args)
            except Exception as e:   # surfaced to the callback; never kill the worker
                if type(e).__name__ != 'HelperError':      # the helper logged its own traceback
                    log.exception('worker task %s failed', name)
                result = e
            self._done.emit(cb, result)

    def _dispatch(self, cb, result) -> None:
        if cb is not None:
            cb(result)

    def shutdown(self) -> None:
        self._closed = True
        while True:                  # drop what is still queued
            try:
                self._q.get_nowait()
            except queue.Empty:
                break
        self._q.put((-1, -1, 0.0, None, (), None))
        if self._helper is not None:
            self._thread.join(timeout=2)
            self._helper.close()
