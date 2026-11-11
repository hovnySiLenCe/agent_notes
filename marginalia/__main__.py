import argparse
import ctypes
import ctypes.util
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUTOSTART = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'autostart' / 'marginalia.desktop'


def _preload_xcb_cursor() -> None:
    """Qt >= 6.5's xcb plugin needs libxcb-cursor0. If the system lacks it, load the copy that
    scripts/setup.sh unpacked so the dynamic loader can satisfy the plugin's dependency by soname."""
    if ctypes.util.find_library('xcb-cursor'):
        return
    local = ROOT / '.venv/syslibs/root/usr/lib/x86_64-linux-gnu/libxcb-cursor.so.0'
    if local.exists():
        ctypes.CDLL(str(local), mode=ctypes.RTLD_GLOBAL)


def _parse(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog='run.sh', description='Marginalia：给 Agent 输出加批注的桌面悬浮工具。'
                                '不带参数时在后台启动（已在运行则显示面板）。')
    g = p.add_mutually_exclusive_group()
    g.add_argument('-f', '--foreground', action='store_true', help='在当前终端前台运行（日志输出到终端，Ctrl+C 退出）')
    g.add_argument('--stop', action='store_true', help='结束正在运行的实例')
    g.add_argument('--restart', action='store_true', help='重启（加载新代码）')
    g.add_argument('--status', action='store_true', help='查看是否在运行')
    g.add_argument('--autostart', choices=('on', 'off'), help='登录桌面时自动启动')
    g.add_argument('--setup-firefox', action='store_true',
                   help='为 Firefox 打开无障碍接口（写入各配置目录的 user.js，重启 Firefox 后生效），用于精确定位与高亮')
    p.add_argument('--detached', action='store_true', help=argparse.SUPPRESS)   # the background child
    return p.parse_args(argv)


def _log_file() -> Path:
    from .config import data_dir
    return data_dir() / 'marginalia.out'


def _stop() -> bool:
    """Ask the running instance to quit; force it if it doesn't answer. True when none is left."""
    from . import ipc
    pid = ipc.request('quit') or ipc.recorded_pid()
    if pid is None:
        return True
    if ipc.wait_gone(pid, 4.0):
        return True
    return ipc.terminate(pid)


def _ensure_single() -> int | None:
    """PID of a responsive running instance; a frozen or stopped one is replaced (it would swallow every start)."""
    from . import ipc
    pid = ipc.request('ping')
    if pid is not None:
        return pid
    stale = ipc.recorded_pid()
    if stale is not None and stale != os.getpid():
        print(f'发现无响应的旧实例（PID {stale}），已结束它。', file=sys.stderr)
        ipc.terminate(stale)
    return None


def _start_background() -> int:
    from . import ipc
    out = open(_log_file(), 'ab')
    child = subprocess.Popen([sys.executable, '-m', 'marginalia', '--detached'], cwd=ROOT,
                             stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                             start_new_session=True)          # own session: closing the terminal won't kill it
    end = time.monotonic() + 15
    while time.monotonic() < end:
        if child.poll() is not None:
            tail = _log_file().read_text(encoding='utf-8', errors='replace').splitlines()[-15:]
            print('启动失败：\n' + '\n'.join(tail), file=sys.stderr)
            return 1
        if ipc.request('ping', timeout=0.5) == child.pid:
            print(f'Marginalia 已在后台运行（PID {child.pid}）。停止：./run.sh --stop　日志：{_log_file()}')
            return 0
        time.sleep(0.2)
    print(f'Marginalia 已在后台启动（PID {child.pid}），但尚未响应；日志：{_log_file()}', file=sys.stderr)
    return 0


def _migrate() -> None:
    """From before the rename to Marginalia: move config/data over and update the autostart entry."""
    from .config import migrate_old_dirs
    try:
        for what in migrate_old_dirs():
            print(f'已迁移旧数据：{what}', file=sys.stderr)
        old = AUTOSTART.with_name('agent-notes.desktop')
        if old.exists():
            old.unlink()
            _autostart(True)
    except OSError as e:
        print(f'迁移旧数据失败：{e}', file=sys.stderr)


def _autostart(on: bool) -> int:
    if not on:
        AUTOSTART.unlink(missing_ok=True)
        print('已关闭开机自启。')
        return 0
    AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
    AUTOSTART.write_text('\n'.join([
        '[Desktop Entry]', 'Type=Application', 'Name=Marginalia', 'Comment=给 Agent 输出加批注',
        f'Exec={ROOT / "run.sh"}', 'Terminal=false', 'X-GNOME-Autostart-enabled=true',
        'X-GNOME-Autostart-Delay=5', '']), encoding='utf-8')
    print(f'已开启开机自启：{AUTOSTART}')
    return 0


FIREFOX_PREF = 'user_pref("accessibility.force_disabled", -1);'
FIREFOX_ROOTS = ('snap/firefox/common/.mozilla/firefox', '.mozilla/firefox')


def firefox_profiles(home: Path | None = None) -> list[Path]:
    home = home or Path.home()
    return sorted({p.parent for root in FIREFOX_ROOTS for p in (home / root).glob('*/prefs.js')})


def setup_firefox(home: Path | None = None) -> int:
    """Snap Firefox ignores the desktop accessibility switch; this pref turns it on (user.js is applied at start)."""
    profiles = firefox_profiles(home)
    if not profiles:
        print('没有找到 Firefox 配置目录。也可以手动：about:config → accessibility.force_disabled 设为 -1，然后重启 Firefox。')
        return 1
    for prof in profiles:
        uj = prof / 'user.js'
        lines = uj.read_text(encoding='utf-8').splitlines() if uj.exists() else []
        lines = [ln for ln in lines if 'accessibility.force_disabled' not in ln] + [FIREFOX_PREF]
        uj.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        print(f'已写入 {uj}')
    print('请完全退出并重新打开 Firefox 后生效。撤销：删除上述 user.js 中这一行，并在 about:config 里重置该项。')
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse(sys.argv[1:] if argv is None else argv)
    _migrate()
    from . import ipc
    if args.status:
        pid = ipc.request('ping')
        print(f'正在运行（PID {pid}）' if pid else '未运行')
        return 0 if pid else 1
    if args.stop:
        ok = _stop()
        print('已停止。' if ok else '无法结束旧实例，请手动 kill。')
        return 0 if ok else 1
    if args.autostart:
        return _autostart(args.autostart == 'on')
    if args.setup_firefox:
        return setup_firefox()
    if args.restart and not _stop():
        print('无法结束旧实例，请手动 kill。', file=sys.stderr)
        return 1

    pid = _ensure_single()
    if pid is not None:
        ipc.request('show')
        if not args.detached:
            print(f'Marginalia 已在运行（PID {pid}），已显示面板。')
        return 0
    if not (args.foreground or args.detached):
        return _start_background()

    _preload_xcb_cursor()
    from .app import run
    return run([sys.argv[0]], log_to_stderr=args.foreground)


if __name__ == '__main__':
    sys.exit(main())
