"""A tiny EWMH window manager for the headless test sandbox (Xvfb has none, and none is installed).

Implements just what Marginalia relies on: _NET_ACTIVE_WINDOW (read + activation requests), _NET_CLIENT_LIST,
_NET_CLIENT_LIST_STACKING, _NET_CURRENT_DESKTOP. No decorations, no reparenting.

Usage:  python -m tests.e2e.miniwm        (DISPLAY must point at the sandbox server)
"""
from __future__ import annotations

import os
import sys

from Xlib import X, Xatom, display, error

d = display.Display()
root = d.screen().root
A = d.intern_atom


def _set_windows(name: str, ids: list[int]) -> None:
    root.change_property(A(name), Xatom.WINDOW, 32, ids)


class WM:
    def __init__(self):
        self.stack: list[int] = []        # bottom → top
        self.active = 0
        self.deferred = 0                 # activation requested before the window became viewable
        catch = error.CatchError(error.BadAccess)
        root.change_attributes(event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask, onerror=catch)
        d.sync()
        if catch.get_error():
            sys.exit('another window manager is running')
        check = root.create_window(-1, -1, 1, 1, 0, X.CopyFromParent)
        for w in (root, check):
            w.change_property(A('_NET_SUPPORTING_WM_CHECK'), Xatom.WINDOW, 32, [check.id])
        check.change_property(A('_NET_WM_NAME'), A('UTF8_STRING'), 8, b'miniwm')
        root.change_property(A('_NET_SUPPORTED'), Xatom.ATOM, 32,
                             [A(n) for n in ('_NET_ACTIVE_WINDOW', '_NET_CLIENT_LIST', '_NET_CLIENT_LIST_STACKING',
                                             '_NET_CURRENT_DESKTOP', '_NET_WM_PID')])
        root.change_property(A('_NET_CURRENT_DESKTOP'), Xatom.CARDINAL, 32, [0])
        self.publish()

    def publish(self) -> None:
        _set_windows('_NET_CLIENT_LIST', self.stack)
        _set_windows('_NET_CLIENT_LIST_STACKING', self.stack)
        _set_windows('_NET_ACTIVE_WINDOW', [self.active])
        d.flush()

    def activate(self, xid: int, why: str = '') -> None:
        if xid not in self.stack:     # asked before its MapRequest arrived (e.g. a popup shown again)
            self.deferred = xid
            return
        if os.environ.get('MINIWM_DEBUG'):
            print(f'[miniwm] activate {xid:#x} ({why})', file=sys.stderr, flush=True)
        self.stack.remove(xid)
        self.stack.append(xid)
        w = d.create_resource_object('window', xid)
        try:
            viewable = w.get_attributes().map_state == X.IsViewable
        except error.XError:
            return
        if not viewable:              # SetInputFocus would fail with BadMatch; focus it once it is mapped
            self.deferred = xid
            return
        self.deferred = 0
        catch = error.CatchError()
        w.configure(stack_mode=X.Above, onerror=catch)
        w.set_input_focus(X.RevertToPointerRoot, X.CurrentTime, onerror=catch)
        d.sync()
        if not catch.get_error():
            self.active = xid
        self.publish()

    def forget(self, xid: int) -> None:
        if xid in self.stack:
            self.stack.remove(xid)
            if self.active == xid:
                self.active = 0
                if self.stack:
                    self.activate(self.stack[-1], 'previous closed')
                    return
            self.publish()

    def wants_focus(self, w) -> bool:
        try:
            t = w.get_full_property(A('_NET_WM_USER_TIME'), Xatom.CARDINAL)
        except error.XError:
            return False
        return not (t and t.value[0] == 0)       # Qt's WA_ShowWithoutActivating sets user time 0

    def run(self) -> None:
        while True:
            e = d.next_event()
            try:
                if e.type == X.MapRequest:
                    e.window.map()
                    e.window.change_attributes(event_mask=X.StructureNotifyMask)
                    if e.window.id not in self.stack:
                        self.stack.append(e.window.id)
                    if self.wants_focus(e.window) or e.window.id == self.deferred:
                        self.activate(e.window.id, 'mapped')
                    else:
                        self.publish()
                elif e.type == X.ConfigureRequest:
                    kw = {k: getattr(e, k) for k, bit in (('x', X.CWX), ('y', X.CWY), ('width', X.CWWidth),
                                                          ('height', X.CWHeight)) if e.value_mask & bit}
                    e.window.configure(**kw)
                    if e.value_mask & X.CWStackMode and e.stack_mode == X.Above and e.window.id in self.stack:
                        self.stack.remove(e.window.id)
                        self.stack.append(e.window.id)
                        e.window.configure(stack_mode=X.Above)
                        self.publish()
                elif e.type == X.MapNotify and e.window.id == self.deferred:
                    self.activate(e.window.id, 'deferred until mapped')
                elif e.type in (X.UnmapNotify, X.DestroyNotify):
                    self.forget(e.window.id)
                elif e.type == X.ClientMessage and e.client_type == A('_NET_ACTIVE_WINDOW'):
                    # Like mutter's focus-stealing prevention: apps raising themselves (source 1, e.g. Firefox
                    # once its page loads) don't get focus; pagers/tools (source 2, Marginalia) do.
                    if e.data[1][0] != 1 or not self.active:
                        self.activate(e.window.id, f'request source={e.data[1][0]}')
            except error.XError:
                pass


if __name__ == '__main__':
    try:
        WM().run()
    except error.ConnectionClosedError:
        pass          # the sandbox X server went away
