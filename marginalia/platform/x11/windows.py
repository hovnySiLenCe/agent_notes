"""EWMH window queries and activation."""
from __future__ import annotations

import threading
import time

from Xlib import X, Xatom, display, error, protocol

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


def primary_owned_by(xid: int, pid: int | None = None) -> bool:
    """Was the PRIMARY selection set by the application of window `xid` (process `pid`)?

    Usually the window's own X client owns it (resource IDs carry the owning client in the bits above
    resource_id_mask). Terminal programs that handle the mouse themselves (Claude Code's interface) set it
    through a helper instead (xclip & co.): then the owner's process descends from the window's process
    (terminal -> shell -> program -> xclip), possibly only through its process group or session once the
    helper has gone to the background."""
    d = xd.get()
    try:
        owner = d.get_selection_owner(xd.atom('PRIMARY'))
    except error.XError:
        return False
    owner_id = owner if isinstance(owner, int) else getattr(owner, 'id', 0)
    if not owner_id:
        return False
    mask = d.display.info.resource_id_mask
    if (owner_id & ~mask) == (xid & ~mask):
        return True
    if not pid:
        return False
    owner_pid = client_pid(owner_id)
    return bool(owner_pid) and pid in _related_pids(owner_pid)


def read_primary(timeout: float = 0.4) -> str:
    """The PRIMARY selection's text, asked for as UTF8_STRING (then STRING). Some owners list more targets than
    they serve (Claude Code advertises text/plain;charset=utf-8 but refuses it), which leaves Qt's reading empty.
    Uses its own X connection: callable from any thread."""
    try:
        d = display.Display()
    except Exception:
        return ''
    try:
        win = d.screen().root.create_window(0, 0, 1, 1, 0, X.CopyFromParent)
        prop = d.intern_atom('MARGINALIA_PRIMARY')
        for target in ('UTF8_STRING', 'STRING'):
            win.convert_selection(Xatom.PRIMARY, d.intern_atom(target), prop, X.CurrentTime)
            d.flush()
            end = time.monotonic() + timeout
            while time.monotonic() < end:
                if not d.pending_events():
                    time.sleep(0.005)
                    continue
                ev = d.next_event()
                if ev.type != X.SelectionNotify:
                    continue
                if ev.property != X.NONE:
                    r = win.get_full_property(prop, X.AnyPropertyType)
                    if r is not None and isinstance(r.value, bytes):
                        return r.value.decode('utf-8' if target == 'UTF8_STRING' else 'latin-1', errors='replace')
                break
        return ''
    except Exception:
        return ''
    finally:
        d.close()


def client_pid(resource: int) -> int | None:
    """PID of the local X client owning `resource` (XRes extension), or None."""
    d = xd.get()
    try:
        if not d.has_extension('X-Resource'):
            return None
        from Xlib.ext import res
        reply = d.res_query_client_ids([{'client': resource, 'mask': res.LocalClientPIDMask}])
        for item in reply.ids:
            if item.value:
                return int(item.value[0])
    except Exception:
        return None
    return None


def _stat(pid: int) -> tuple[int, int, int] | None:
    """(parent, process group, session) from /proc."""
    try:
        with open(f'/proc/{pid}/stat') as f:
            fields = f.read().rsplit(')', 1)[1].split()
        return int(fields[1]), int(fields[2]), int(fields[3])
    except (OSError, IndexError, ValueError):
        return None


def _related_pids(pid: int) -> set[int]:
    """`pid`'s ancestors, and those of its process group leader and session leader."""
    out: set[int] = set()
    todo = [pid]
    while todo and len(out) < 256:
        p = todo.pop()
        if p <= 1 or p in out:
            continue
        out.add(p)
        st = _stat(p)
        if st:
            todo.extend(st)
    return out


def compositing() -> bool:
    """Is a compositing manager running? Without one, translucent windows are painted opaque."""
    d = xd.get()
    try:
        owner = d.get_selection_owner(xd.atom(f'_NET_WM_CM_S{d.get_default_screen()}'))
    except error.XError:
        return True
    return bool(owner if isinstance(owner, int) else getattr(owner, 'id', 0))


def server_time() -> int:
    """A real X server timestamp. mutter refuses _NET_ACTIVE_WINDOW requests stamped CurrentTime."""
    d = xd.get()
    w = getattr(_local, 'ts_window', None)
    if w is None:
        w = _local.ts_window = xd.root().create_window(-10, -10, 1, 1, 0, X.CopyFromParent,
                                                       event_mask=X.PropertyChangeMask)
    w.change_property(xd.atom('_MARGINALIA_TS'), Xatom.STRING, 8, b'x')
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


# ---- geometry & stacking (for clipping highlights) --------------------------------------------------------------
Rect = tuple[int, int, int, int]      # x, y, w, h in physical screen pixels


def _cardinals(win, name: str) -> list[int]:
    v = _prop(win, name, Xatom.CARDINAL)
    return [int(x) for x in v] if v is not None else []


def client_rect(xid: int) -> Rect | None:
    """Content area of the window on screen (excluding WM decorations and GTK client-side shadows)."""
    w = _window(xid)
    try:
        g = w.get_geometry()
        o = w.translate_coords(xd.root(), 0, 0)
    except error.XError:
        return None
    x, y, wd, ht = -o.x, -o.y, g.width, g.height
    gtk = _cardinals(w, '_GTK_FRAME_EXTENTS')         # left, right, top, bottom shadow margins inside the window
    if len(gtk) == 4:
        x, y, wd, ht = x + gtk[0], y + gtk[2], wd - gtk[0] - gtk[1], ht - gtk[2] - gtk[3]
    return (x, y, wd, ht)


def frame_rect(xid: int) -> Rect | None:
    """Everything the window covers on screen, including server-side decorations (title bar)."""
    r = client_rect(xid)
    if r is None:
        return None
    ext = _cardinals(_window(xid), '_NET_FRAME_EXTENTS')
    if len(ext) == 4:
        return (r[0] - ext[0], r[1] - ext[2], r[2] + ext[0] + ext[1], r[3] + ext[2] + ext[3])
    return r


def is_shown(xid: int) -> bool:
    """Mapped, not minimized, and on the current workspace."""
    w = _window(xid)
    try:
        if w.get_attributes().map_state != X.IsViewable:
            return False
    except error.XError:
        return False
    state = _prop(w, '_NET_WM_STATE', Xatom.ATOM)
    if state is not None and xd.atom('_NET_WM_STATE_HIDDEN') in list(state):
        return False
    desk = _cardinals(w, '_NET_WM_DESKTOP')
    cur = _cardinals(xd.root(), '_NET_CURRENT_DESKTOP')
    return not desk or not cur or desk[0] in (cur[0], 0xFFFFFFFF)


def stacking() -> list[int]:
    """Managed windows, bottom to top."""
    v = _prop(xd.root(), '_NET_CLIENT_LIST_STACKING')
    return [int(w) for w in v] if v is not None else client_list()


def occluders(xid: int) -> list[Rect]:
    """Screen areas of the windows stacked above `xid` that are currently shown."""
    order = stacking()
    if xid not in order:
        return []
    out = []
    for w in order[order.index(xid) + 1:]:
        if is_shown(w):
            r = frame_rect(w)
            if r and r[2] > 0 and r[3] > 0:
                out.append(r)
    return out
