"""Single background thread for blocking platform calls (AT-SPI D-Bus, X round-trips).

Calls to the platform's own methods (`worker.submit(platform.track, ...)`) are forwarded to the helper process
(helper.py), so a native crash in an accessibility query can't take the app down. Results are delivered back on
the Qt main thread through a queued signal.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)


class Worker(QObject):
    _done = Signal(object, object)   # callback, result (or exception)

    def __init__(self, remote: object | None = None, helper=None):
        """remote: the object whose bound methods run in `helper` (a helper.Helper) instead of this process."""
        super().__init__()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='agent-notes-worker')
        self._remote, self._helper = remote, helper
        self._done.connect(self._dispatch)

    def submit(self, fn: Callable, *args, cb: Callable | None = None) -> None:
        name = getattr(fn, '__name__', str(fn))
        remote = self._helper is not None and getattr(fn, '__self__', None) is self._remote

        def run():
            try:
                result = self._helper.call(name, *args) if remote else fn(*args)
            except Exception as e:   # surfaced to the callback; never kill the worker
                if type(e).__name__ != 'HelperError':      # the helper logged its own traceback
                    log.exception('worker task %s failed', name)
                result = e
            self._done.emit(cb, result)
        try:
            self._pool.submit(run)
        except RuntimeError:         # shutting down: timers may still fire once
            pass

    def _dispatch(self, cb, result) -> None:
        if cb is not None:
            cb(result)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
        if self._helper is not None:
            self._helper.close()
