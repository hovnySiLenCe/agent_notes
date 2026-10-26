"""Spike X11 helpers: find window by pid, activate it, read active window."""
import time
from Xlib import X, display, protocol

d = display.Display()
root = d.screen().root
A = lambda n: d.intern_atom(n)

def client_windows():
    return root.get_full_property(A('_NET_CLIENT_LIST'), X.AnyPropertyType).value

def window_pid(wid):
    w = d.create_resource_object('window', wid)
    p = w.get_full_property(A('_NET_WM_PID'), X.AnyPropertyType)
    return p.value[0] if p else None

def windows_for_pids(pids):
    return [w for w in client_windows() if window_pid(w) in pids]

_tw = None

def server_time():
    """Get a real X server timestamp (mutter rejects activation with CurrentTime)."""
    global _tw
    if _tw is None:
        _tw = root.create_window(-10, -10, 1, 1, 0, X.CopyFromParent, event_mask=X.PropertyChangeMask)
    _tw.change_property(A('_AN_TS'), A('STRING'), 8, b'x')
    d.flush()
    while True:
        e = d.next_event()
        if e.type == X.PropertyNotify and e.window == _tw:
            return e.time

def activate(wid):
    w = d.create_resource_object('window', wid)
    ev = protocol.event.ClientMessage(window=w, client_type=A('_NET_ACTIVE_WINDOW'),
                                      data=(32, [2, server_time(), 0, 0, 0]))
    root.send_event(ev, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
    d.flush()

def active_window():
    p = root.get_full_property(A('_NET_ACTIVE_WINDOW'), X.AnyPropertyType)
    return p.value[0] if p else None
