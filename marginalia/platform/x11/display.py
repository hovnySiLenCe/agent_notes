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
    """Interned atom, cached (atoms never change while the server runs; interning is a round trip)."""
    cache = getattr(_local, 'atoms', None)
    if cache is None:
        cache = _local.atoms = {}
    a = cache.get(name)
    if a is None:
        a = cache[name] = get().intern_atom(name)
    return a


def root():
    return get().screen().root
