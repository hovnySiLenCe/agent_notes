"""Talking to the running instance: one per user and X display, over a Unix socket. No Qt here, so the
command line (`--status`, `--stop`, …) answers instantly without starting a GUI.

Protocol: the client sends one command line (`ping`, `show`, `quit`); the server replies `ok <pid>`.
"""
from __future__ import annotations

import os
import socket
import time
from pathlib import Path

COMMANDS = ('ping', 'show', 'quit')


def _display_tag() -> str:
    return ''.join(c if c.isalnum() else '_' for c in os.environ.get('DISPLAY', '')) or 'nodisplay'


def runtime_dir() -> Path:
    base = os.environ.get('XDG_RUNTIME_DIR')
    p = Path(base) if base and os.path.isdir(base) else Path('/tmp') / f'agent-notes-{os.getuid()}'
    if len(str(p)) > 80:              # Unix socket paths are limited to 108 bytes
        p = Path('/tmp') / f'agent-notes-{os.getuid()}'
    p.mkdir(mode=0o700, parents=True, exist_ok=True)
    return p


def socket_path() -> Path:
    return runtime_dir() / f'agent-notes-{_display_tag()}.sock'


def pid_path() -> Path:
    return runtime_dir() / f'agent-notes-{_display_tag()}.pid'


def request(cmd: str, timeout: float = 2.0) -> int | None:
    """Send `cmd` to the running instance; its PID when it answered, None when nobody (responsive) is there."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(str(socket_path()))
        s.sendall(cmd.encode() + b'\n')
        reply = b''
        while not reply.endswith(b'\n'):
            chunk = s.recv(64)
            if not chunk:
                break
            reply += chunk
    except OSError:
        return None
    finally:
        s.close()
    parts = reply.decode(errors='replace').split()
    return int(parts[1]) if len(parts) == 2 and parts[0] == 'ok' and parts[1].isdigit() else None


def recorded_pid() -> int | None:
    """PID written by the instance that owns the socket, if that process still is Agent Notes."""
    try:
        pid = int(pid_path().read_text().strip())
        cmd = Path(f'/proc/{pid}/cmdline').read_bytes()
    except (OSError, ValueError):
        return None
    return pid if b'agent_notes' in cmd else None


def wait_gone(pid: int, timeout: float) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if not Path(f'/proc/{pid}').exists():
            return True
        time.sleep(0.1)
    return not Path(f'/proc/{pid}').exists()


def terminate(pid: int) -> bool:
    """SIGTERM, then SIGKILL if it does not exit (a stopped or frozen instance)."""
    for sig, wait in ((15, 3.0), (9, 2.0)):
        try:
            os.kill(pid, 18)          # SIGCONT first: a stopped process can't act on SIGTERM
            os.kill(pid, sig)
        except ProcessLookupError:
            return True
        if wait_gone(pid, wait):
            return True
    return False
