"""Run a command inside an invisible desktop: Xvfb + private D-Bus session (own AT-SPI bus) + miniwm.

Nothing appears on the real screen, no focus is stolen and the real clipboard is untouched, so end-to-end tests
can run while you keep working.

Usage:  .venv/bin/python -m tests.e2e.sandbox [--size 1600x1000] -- <command ...>
        .venv/bin/python -m tests.e2e.sandbox -- .venv/bin/python -m tests.e2e.run_e2e firefox
Xvfb: on PATH, or extracted locally by scripts/setup.sh --test into .venv/syslibs/bin.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Session-specific variables from the real desktop that would leak the real bus / input method into the sandbox.
DROP = ('DBUS_SESSION_BUS_ADDRESS', 'AT_SPI_BUS_ADDRESS', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'GTK_IM_MODULE',
        'QT_IM_MODULE', 'XMODIFIERS', 'SESSION_MANAGER', 'GNOME_KEYRING_CONTROL', 'SSH_AUTH_SOCK',
        'GNOME_TERMINAL_SCREEN', 'GNOME_TERMINAL_SERVICE', 'GIO_LAUNCHED_DESKTOP_FILE', 'GIO_LAUNCHED_DESKTOP_FILE_PID')


BUS_PREFIX = '/tmp/dbus-marginalia-sandbox-'


def _kill_bus_children(n: int) -> None:
    """Services the private bus activated (portals, snap userd, at-spi …) outlive it: stop them by their
    environment, which names this sandbox's bus. Never touches anything else."""
    tag = f'{BUS_PREFIX}{n},'.encode()          # the address is followed by ',guid=…'
    for pid in filter(str.isdigit, os.listdir('/proc')):
        if int(pid) == os.getpid():
            continue
        try:
            with open(f'/proc/{pid}/environ', 'rb') as f:
                if tag in f.read():
                    os.kill(int(pid), 15)
        except OSError:
            continue


def find_xvfb() -> str:
    local = ROOT / '.venv/syslibs/bin/Xvfb'
    found = shutil.which('Xvfb') or (str(local) if local.exists() else None)
    if not found:
        sys.exit('Xvfb not found: run scripts/setup.sh --test (no sudo needed) or apt install xvfb')
    return found


def free_display() -> int:
    for n in range(90, 200):
        if not Path(f'/tmp/.X11-unix/X{n}').exists() and not Path(f'/tmp/.X{n}-lock').exists():
            return n
    sys.exit('no free X display number')


def main(argv: list[str]) -> int:
    size = '1600x1000'
    if argv[:1] == ['--size']:
        size, argv = argv[1], argv[2:]
    if argv[:1] == ['--']:
        argv = argv[1:]
    if not argv:
        sys.exit(__doc__)
    n = free_display()
    xvfb = subprocess.Popen([find_xvfb(), f':{n}', '-screen', '0', f'{size}x24', '-nolisten', 'tcp', '-noreset'],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs = [xvfb]
    try:
        for _ in range(100):
            if Path(f'/tmp/.X11-unix/X{n}').exists():
                break
            time.sleep(0.05)
        else:
            sys.exit('Xvfb did not start')
        env = {k: v for k, v in os.environ.items() if k not in DROP}
        env.update(DISPLAY=f':{n}', XDG_SESSION_TYPE='x11', GNOME_ACCESSIBILITY='1', QT_ACCESSIBILITY='1',
                   GTK_IM_MODULE='gtk-im-context-simple', QT_IM_MODULE='simple', NO_AT_BRIDGE='0',
                   LIBGL_ALWAYS_SOFTWARE='1', MARGINALIA_SANDBOX='1')
        # One private session bus for the WM, the apps under test and the test driver (AT-SPI rides on it).
        # Abstract socket named @/tmp/dbus-*: snap apps (Firefox) have a private /tmp and their AppArmor profile
        # only allows abstract sockets with that prefix.
        # The address comes back on a private pipe: services the bus activates inherit its stdout and would
        # otherwise keep our caller's pipe open (and block once it fills).
        rfd, wfd = os.pipe()
        daemon = '/usr/bin/dbus-daemon' if Path('/usr/bin/dbus-daemon').exists() else 'dbus-daemon'
        bus = subprocess.Popen([daemon, '--session', '--nofork', f'--print-address={wfd}',
                                f'--address=unix:abstract={BUS_PREFIX}{n}'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, pass_fds=(wfd,), env=env)
        os.close(wfd)
        procs.append(bus)
        with os.fdopen(rfd) as f:
            env['DBUS_SESSION_BUS_ADDRESS'] = f.readline().strip()
        # Turn accessibility on for this session (the launcher does not see the desktop's gsettings switch here);
        # Firefox & co. only expose their AT-SPI tree when org.a11y.Status says so.
        subprocess.run(['dbus-send', '--session', '--print-reply', '--dest=org.a11y.Bus', '/org/a11y/bus',
                        'org.freedesktop.DBus.Properties.Set', 'string:org.a11y.Status', 'string:IsEnabled',
                        'variant:boolean:true'], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        procs.append(subprocess.Popen([sys.executable, '-m', 'tests.e2e.miniwm'], cwd=ROOT, env=env))
        time.sleep(0.3)
        print(f'[sandbox] DISPLAY=:{n} {size}', flush=True)
        return subprocess.call(argv, cwd=ROOT, env=env)
    finally:
        _kill_bus_children(n)
        for p in reversed(procs):
            p.terminate()
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
