"""Single background thread for blocking platform calls (AT-SPI D-Bus, X round-trips).

Results are delivered back on the Qt main thread through a queued signal.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)


class Worker(QObject):
    _done = Signal(object, object)   # callback, result (or exception)

    def __init__(self):
        super().__init__()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='agent-notes-worker')
        self._done.connect(self._dispatch)

    def submit(self, fn: Callable, *args, cb: Callable | None = None) -> None:
        def run():
            try:
                result = fn(*args)
            except Exception as e:   # surfaced to the callback; never kill the worker
                log.exception('worker task %s failed', getattr(fn, '__name__', fn))
                result = e
            self._done.emit(cb, result)
        self._pool.submit(run)

    def _dispatch(self, cb, result) -> None:
        if cb is not None:
            cb(result)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
