import ctypes
import ctypes.util
import sys
from pathlib import Path


def _preload_xcb_cursor() -> None:
    """Qt >= 6.5's xcb plugin needs libxcb-cursor0. If the system lacks it, load the copy that
    scripts/setup.sh unpacked so the dynamic loader can satisfy the plugin's dependency by soname."""
    if ctypes.util.find_library('xcb-cursor'):
        return
    local = Path(__file__).resolve().parent.parent / '.venv/syslibs/root/usr/lib/x86_64-linux-gnu/libxcb-cursor.so.0'
    if local.exists():
        ctypes.CDLL(str(local), mode=ctypes.RTLD_GLOBAL)


def main() -> int:
    _preload_xcb_cursor()
    from .app import run
    return run(sys.argv)


if __name__ == '__main__':
    sys.exit(main())
