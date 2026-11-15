"""Platform queries (AT-SPI, X) in a separate helper process.

libatspi can take the whole process down with a SIGSEGV when an application destroys accessible objects while
we query them (seen with VS Code's chat webview, inside atspi_accessible_get_state_set). Python can't catch that,
so the queries run in a child process: if it crashes or hangs, only that call fails and the next call starts a
fresh helper. The panel, hotkeys and data stay in the main process.

Protocol: pickled (method name, args) -> ('ok', result) | ('err', message), over a socketpair.
"""
from __future__ import annotations

import faulthandler
import logging
import os
import signal
import socket
import subprocess
import sys
import time
from multiprocessing.connection import Connection
from pathlib import Path

log = logging.getLogger(__name__)

CALL_TIMEOUT = 15.0      # s; a call that takes longer is treated as hung (the helper is killed)
RECYCLE_S = 600.0        # s; an older helper is replaced before its next background call (see Helper.call)
BACKGROUND = {'track'}   # calls that may pay for a fresh helper's start (the user isn't waiting on them)
ROOT = Path(__file__).resolve().parent.parent


class HelperError(RuntimeError):
    pass


class Helper:
    """Owned by the worker thread: calls are sequential, never concurrent."""

    def __init__(self, own_pid: int):
        self.own_pid = own_pid
        self._proc: subprocess.Popen | None = None
        self._conn: Connection | None = None
        self._started = 0.0
        self.restarts = 0

    def _start(self) -> None:
        parent, child = socket.socketpair()
        env = dict(os.environ, PYTHONPATH=os.pathsep.join(p for p in (str(ROOT), os.environ.get('PYTHONPATH')) if p))
        self._proc = subprocess.Popen([sys.executable, '-m', 'marginalia.helper', str(child.fileno()),
                                       str(self.own_pid)], pass_fds=[child.fileno()], env=env,
                                      stdin=subprocess.DEVNULL)
        child.close()
        self._conn = Connection(parent.detach())
        self._started = time.monotonic()

    def _stop(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        if self._proc is not None:
            if self._proc.poll() is None:
                self._proc.kill()
            self._proc.wait(2)
            self._proc = None

    def call(self, name: str, *args):
        # libatspi keeps a copy of apps' trees (Chromium's in full) and needs their change signals to keep it
        # right; a long-lived process ends up asking about nodes that are gone (seen: VS Code captures and
        # highlights failing after a day). A fresh helper every few minutes, swapped in on a background call.
        if self._proc is not None and name in BACKGROUND and time.monotonic() - self._started > RECYCLE_S:
            self._stop()
        if self._proc is None or self._proc.poll() is not None:
            if self._proc is not None:
                self._stop()
            self._start()
        try:
            self._conn.send((name, args))
            if not self._conn.poll(CALL_TIMEOUT):
                raise TimeoutError
            kind, value = self._conn.recv()
        except (EOFError, OSError, TimeoutError) as e:
            what = 'hung' if isinstance(e, TimeoutError) else 'crashed'
            proc = self._proc
            self._stop()                                    # kills it if it is still running
            log.error('helper %s during %s (exit code %s); a new one starts with the next call',
                      what, name, proc.returncode if proc else None)
            self.restarts += 1
            raise HelperError(f'helper {what} in {name}') from None
        if kind == 'err':
            raise HelperError(value)
        return value

    def close(self) -> None:
        self._stop()


def _serve(fd: int, own_pid: int) -> None:
    signal.signal(signal.SIGINT, signal.SIG_IGN)          # Ctrl+C in a foreground run is the parent's business
    faulthandler.enable()
    from . import config as cfgmod
    logging.basicConfig(level=logging.DEBUG if os.environ.get('MARGINALIA_DEBUG') else logging.INFO, format='%(asctime)s %(levelname)s %(name)s [helper]: %(message)s',
                        handlers=[logging.FileHandler(cfgmod.data_dir() / 'marginalia.log', encoding='utf-8')])
    from .platform.base import get_platform
    platform = get_platform(own_pid)
    conn = Connection(fd)
    from gi.repository import GLib
    ctx = GLib.MainContext.default()
    while True:
        try:
            while not conn.poll(0.05):     # meanwhile deliver libatspi's D-Bus signals (its cache updates)
                for _ in range(1000):
                    if not ctx.pending():
                        break
                    ctx.iteration(False)
            name, args = conn.recv()
        except (EOFError, OSError):                         # the main process went away
            return
        t = time.monotonic()
        try:
            reply = ('ok', getattr(platform, name)(*args))
        except Exception as e:
            logging.getLogger('marginalia.helper').exception('%s failed', name)
            reply = ('err', f'{type(e).__name__}: {e}')
        if time.monotonic() - t > 5:
            logging.getLogger('marginalia.helper').warning('%s took %.1f s', name, time.monotonic() - t)
        try:
            conn.send(reply)
        except Exception:                                   # e.g. an unpicklable result
            conn.send(('err', f'{name}: result could not be sent back'))


if __name__ == '__main__':
    _serve(int(sys.argv[1]), int(sys.argv[2]))
