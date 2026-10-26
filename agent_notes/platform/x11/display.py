"""Per-thread Xlib connections: python-xlib Display objects are not thread-safe."""
from __future__ import annotations

import threading

from Xlib import display

_local = threading.local()


def get() -> display.Display:
    d = getattr(_local, 'display', None)
    if d is None:
        d = _local.display = display.Display()
    return d


def atom(name: str) -> int:
    return get().intern_atom(name)


def root():
    return get().screen().root
