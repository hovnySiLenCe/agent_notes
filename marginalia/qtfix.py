"""Workarounds for bugs in specific PySide6 releases."""
from __future__ import annotations

import ctypes
import logging
import sys

from PySide6 import __version__ as pyside_version
from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)


class _Probe(QObject):
    fired = Signal()


def emit_drops_true() -> bool:
    """PySide6 6.12.0: every Signal.emit() releases one reference to True that it never took. Once the count
    reaches zero Python frees the static True object and the process aborts with 'free(): invalid pointer'
    (after a few thousand emits; the selection bubble emits on every mouse click)."""
    p = _Probe()
    before = sys.getrefcount(True)
    for _ in range(8):
        p.fired.emit()
    return sys.getrefcount(True) < before - 4


def apply() -> None:
    if sys.implementation.name != 'cpython' or sys.version_info >= (3, 12):   # 3.12+: True is immortal
        return
    if not emit_drops_true():
        return
    # Make True effectively immortal (what CPython 3.12 does for it): ob_refcnt is the object's first field.
    ctypes.c_ssize_t.from_address(id(True)).value += 1 << 40
    log.warning('PySide6 %s drops a reference to True on every signal emit; worked around. '
                'Run ./scripts/setup.sh to install a fixed version.', pyside_version)
