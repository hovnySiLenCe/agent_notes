"""EWMH window queries and activation."""
from __future__ import annotations

import threading
import time

from Xlib import X, Xatom, error, protocol

from ..base import WindowInfo
from . import display as xd

_local = threading.local()


def _window(xid: int):
    return xd.get().create_resource_object('window', xid)


def _prop(win, name: str, type_=X.AnyPropertyType):
    try:
        p = win.get_full_property(xd.atom(name), type_)
    except error.XError:
        return None
    return p.value if p else None


def active_xid() -> int | None:
    v = _prop(xd.root(), '_NET_ACTIVE_WINDOW')
    return int(v[0]) if v is not None and len(v) and v[0] else None


def client_list() -> list[int]:
    v = _prop(xd.root(), '_NET_CLIENT_LIST')
    return [int(w) for w in v] if v is not None else []


def info(xid: int) -> WindowInfo | None:
    w = _window(xid)
    try:
        pid = _prop(w, '_NET_WM_PID')
        cls = w.get_wm_class() or ('', '')
        name = _prop(w, '_NET_WM_NAME', xd.atom('UTF8_STRING'))
        if name is None:
            name = _prop(w, 'WM_NAME', Xatom.STRING)
    except error.XError:
        return None
    title = name.decode('utf-8', 'replace') if isinstance(name, bytes) else (name or '')
    return WindowInfo(xid=xid, pid=int(pid[0]) if pid is not None and len(pid) else None,
                      wm_instance=cls[0] or '', wm_class=cls[1] or '', title=title)


def active_window() -> WindowInfo | None:
    xid = active_xid()
    return info(xid) if xid else None


def exists(xid: int) -> bool:
    return xid in client_list()


def primary_owned_by(xid: int) -> bool:
    """Is the PRIMARY selection owned by the same X client (application) as window `xid`?
    Resource IDs carry the owning client in the bits above resource_id_mask."""
    d = xd.get()
    try:
        owner = d.get_selection_owner(xd.atom('PRIMARY'))
    except error.XError:
        return False
    owner_id = owner if isinstance(owner, int) else getattr(owner, 'id', 0)
    if not owner_id:
        return False
    mask = d.display.info.resource_id_mask
    return (owner_id & ~mask) == (xid & ~mask)


def server_time() -> int:
    """A real X server timestamp. mutter refuses _NET_ACTIVE_WINDOW requests stamped CurrentTime."""
    d = xd.get()
    w = getattr(_local, 'ts_window', None)
    if w is None:
        w = _local.ts_window = xd.root().create_window(-10, -10, 1, 1, 0, X.CopyFromParent,
                                                       event_mask=X.PropertyChangeMask)
    w.change_property(xd.atom('_AGENT_NOTES_TS'), Xatom.STRING, 8, b'x')
    d.flush()
    while True:
        e = d.next_event()
        if e.type == X.PropertyNotify and e.window == w:
            return e.time


def activate(xid: int) -> None:
    ev = protocol.event.ClientMessage(window=_window(xid), client_type=xd.atom('_NET_ACTIVE_WINDOW'),
                                      data=(32, [2, server_time(), 0, 0, 0]))   # 2 = pager/tool request
    xd.root().send_event(ev, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
    xd.get().flush()


def wait_active(xid: int, timeout: float = 1.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if active_xid() == xid:
            return True
        time.sleep(0.04)
    return active_xid() == xid
