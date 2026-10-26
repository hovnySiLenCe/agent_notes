"""End-to-end test on a live X11 desktop.

Drives the real app with synthetic input against throwaway Firefox / gnome-terminal / VS Code instances that
this script starts itself (GPU disabled, nice 19). Safety: every synthetic key/mouse event is preceded by a
check that the active window is the one we expect, so nothing is ever typed into a window we did not open.

Usage:  .venv/bin/python -m tests.e2e.run_e2e [firefox] [terminal] [vscode]     (default: all)
"""
from __future__ import annotations

import json
import os
import random
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from agent_notes.__main__ import _preload_xcb_cursor

_preload_xcb_cursor()

from PySide6.QtGui import QClipboard, QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from Xlib import X  # noqa: E402
from Xlib.ext import xtest  # noqa: E402

from agent_notes import config as cfgmod  # noqa: E402
from agent_notes.core.composer import compose  # noqa: E402
from agent_notes.core.models import Annotation  # noqa: E402
from agent_notes.platform.atspi.geometry import vte_rects  # noqa: E402
from agent_notes.platform.atspi.tree import Atspi, S, T, walk  # noqa: E402
from agent_notes.platform.x11 import display as xd, keys, windows  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / 'tests/e2e/fixtures'
WORK = ROOT / 'tests/e2e/_work'          # not hidden: snap Firefox cannot read hidden dirs
ORIGINAL_CLIPBOARD = 'E2E-ORIGINAL-CLIPBOARD'


class Abort(Exception):
    pass


class Harness:
    def __init__(self):
        self.qapp = QApplication.instance() or QApplication(sys.argv)
        self.run_dir = WORK / time.strftime('run-%Y%m%d-%H%M%S')
        (self.run_dir / 'shots').mkdir(parents=True, exist_ok=True)
        self.results: list[tuple[str, bool, str]] = []
        self.cleanups: list = []
        self.app_proc: subprocess.Popen | None = None

    # ---- plumbing -------------------------------------------------------------------------------------------
    def pump(self, sec: float) -> None:
        end = time.monotonic() + sec
        while time.monotonic() < end:
            self.qapp.processEvents()
            time.sleep(0.02)

    def wait(self, fn, timeout: float = 5.0, interval: float = 0.1):
        end = time.monotonic() + timeout
        while True:
            v = fn()
            if v or time.monotonic() > end:
                return v
            self.pump(interval)

    def check(self, name: str, ok: bool, detail: str = '') -> bool:
        self.results.append((name, bool(ok), detail))
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f'  — {detail}' if detail and not ok else ''), flush=True)
        return bool(ok)

    def ensure_active(self, xid: int) -> None:
        if windows.active_xid() != xid:
            raise Abort(f'active window is {windows.active_xid()}, expected {xid}; refusing to send input')

    def key(self, combo: str, expect_xid: int) -> None:
        self.ensure_active(expect_xid)
        keys.send(combo)

    def drag(self, x0: int, y: int, x1: int, expect_xid: int) -> None:
        d = xd.get()
        self.ensure_active(expect_xid)
        xtest.fake_input(d, X.MotionNotify, x=x0, y=y)
        xtest.fake_input(d, X.ButtonPress, 1)
        d.sync()
        for i in range(1, 9):
            xtest.fake_input(d, X.MotionNotify, x=x0 + (x1 - x0) * i // 8, y=y)
            d.sync()
            time.sleep(0.02)
        xtest.fake_input(d, X.ButtonRelease, 1)
        d.sync()

    def activate(self, xid: int) -> None:
        windows.activate(xid)
        if not windows.wait_active(xid, 2.0):
            raise Abort(f'could not activate test window {xid}')

    def pids_matching(self, pattern: str) -> set[int]:
        out = subprocess.run(['pgrep', '-f', pattern], capture_output=True, text=True).stdout.split()
        return {int(p) for p in out}

    def windows_of(self, pids: set[int]) -> list[int]:
        return [w for w in windows.client_list() if (windows.info(w) or None) and windows.info(w).pid in pids]

    def window_titled(self, title: str) -> int | None:
        return next((w for w in windows.client_list() if title in ((windows.info(w) or None) and windows.info(w).title or '')), None)

    def shot(self, name: str, xid: int) -> None:
        try:
            w = xd.get().create_resource_object('window', xid)
            g, o = w.get_geometry(), w.translate_coords(xd.root(), 0, 0)
            scr = QGuiApplication.primaryScreen()
            r = scr.devicePixelRatio()     # grabWindow takes logical coords; X gives physical pixels
            pm = scr.grabWindow(0, int(-o.x / r), int(-o.y / r), int(g.width / r), int(g.height / r))
            pm.save(str(self.run_dir / 'shots' / f'{name}.png'))
        except Exception as e:
            print('   (screenshot failed:', e, ')')

    # ---- app under test -------------------------------------------------------------------------------------
    def start_app(self) -> None:
        env = dict(os.environ, AGENT_NOTES_CONFIG_DIR=str(self.run_dir / 'config'),
                   AGENT_NOTES_DATA_DIR=str(self.run_dir / 'data'))
        log = open(self.run_dir / 'app.log', 'w')
        self.app_proc = subprocess.Popen(['nice', '-n', '19', sys.executable, '-m', 'agent_notes'],
                                         cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        ok = self.wait(lambda: self.panel_xid(), 15)
        if not self.check('app starts and shows the floating panel', ok):
            raise Abort('app did not start; see ' + str(self.run_dir / 'app.log'))

    def panel_xid(self) -> int | None:
        for w in windows.client_list():
            i = windows.info(w)
            if i and self.app_proc and i.pid == self.app_proc.pid and i.title == 'Agent Notes':
                return w
        return None

    def app_active(self) -> int | None:
        i = windows.active_window()
        return i.xid if i and self.app_proc and i.pid == self.app_proc.pid else None

    def db(self) -> list[dict]:
        p = self.run_dir / 'data' / 'notes.db'
        if not p.exists():
            return []
        con = sqlite3.connect(p)
        con.row_factory = sqlite3.Row
        rows = [dict(r) for r in con.execute('SELECT * FROM annotations ORDER BY sort_order')]
        con.close()
        for r in rows:
            r['anchor'], r['source'] = json.loads(r['anchor']), json.loads(r['source'])
        return rows

    def popup_type(self, text: str, popup_xid: int) -> None:
        """Paste into the popup's comment box: IME-independent (the desktop runs a pinyin engine) and realistic."""
        QGuiApplication.clipboard().setText(text, QClipboard.Clipboard)
        self.pump(0.2)
        self.key('ctrl+v', popup_xid)
        self.pump(0.3)

    def annotate(self, target_xid: int, hotkey: str, type_digit: str | None, comment: str | None) -> bool:
        before = len(self.db())
        self.key(hotkey, target_xid)
        popup = self.wait(self.app_active, 4)
        if not self.check(f'{hotkey}: popup opens and takes focus', popup):
            tail = (self.run_dir / 'app.log').read_text(encoding='utf-8').splitlines()[-3:]
            print('   app log tail:', tail)
            return False
        self.pump(0.2)
        self.shot(f"popup_{hotkey.replace('+', '_')}", popup)
        if type_digit:
            self.key(type_digit, popup)
            self.pump(0.2)
        if comment:
            self.popup_type(comment, popup)
        self.key('Return', popup)
        saved = self.wait(lambda: len(self.db()) == before + 1, 3)
        self.check('annotation saved', saved)
        self.check('focus handed back to the source window', self.wait(lambda: windows.active_xid() == target_xid, 2))
        return bool(saved)

    def expected_fill(self, rows: list[dict]) -> str:
        cfg, _ = cfgmod.Config.load(self.run_dir / 'config' / 'config.json')
        items = [Annotation(type_id=r['type_id'], quote=r['quote'], comment=r['comment']) for r in rows]
        return compose(items, cfg.type_map, cfg.prompt)

    def close(self) -> None:
        for fn in reversed(self.cleanups):
            try:
                fn()
            except Exception as e:
                print('cleanup error:', e)
        if self.app_proc:
            self.app_proc.terminate()
            try:
                self.app_proc.wait(5)
            except subprocess.TimeoutExpired:
                self.app_proc.kill()

    # ---- helpers for test apps ----------------------------------------------------------------------------
    def kill_matching(self, pattern: str) -> None:
        """SIGTERM, then SIGKILL survivors (VS Code's main process may ignore TERM and respawn helpers)."""
        for sig in (15, 9):
            for p in self.pids_matching(pattern):
                try:
                    os.kill(p, sig)
                except ProcessLookupError:
                    pass
            if not self.wait(lambda: not self.pids_matching(pattern), 3):
                continue
            return

    def select_text(self, pids: set[int], quote: str) -> bool:
        """Like a fresh mouse selection: drop any previous selection, then select `quote`."""
        desk = Atspi.get_desktop(0)
        for a in (desk.get_child_at_index(i) for i in range(desk.get_child_count())):
            if a is None or a.get_process_id() not in pids:
                continue
            for node, _, _ in walk(a, time.monotonic() + 3, prune_hidden=False):
                try:
                    for k in reversed(range(T.get_n_selections(node))):
                        T.remove_selection(node, k)
                except Exception:
                    continue
        for a in (desk.get_child_at_index(i) for i in range(desk.get_child_count())):
            if a is None or a.get_process_id() not in pids:
                continue
            for node, _, _ in walk(a, time.monotonic() + 3, prune_hidden=False):
                try:
                    if node.get_role_name() == 'static':
                        continue
                    s = T.get_text(node, 0, T.get_character_count(node))
                except Exception:
                    continue
                i = s.find(quote)
                if i >= 0:
                    if T.get_n_selections(node):
                        return T.set_selection(node, 0, i, i + len(quote))
                    return T.add_selection(node, i, i + len(quote))
        return False

    def find_entry(self, pids: set[int], name_part: str):
        desk = Atspi.get_desktop(0)
        for a in (desk.get_child_at_index(i) for i in range(desk.get_child_count())):
            if a is None or a.get_process_id() not in pids:
                continue
            for node, _, _ in walk(a, time.monotonic() + 3, prune_hidden=False):
                try:
                    if node.get_role_name() == 'entry' and name_part in (node.get_name() or ''):
                        return node
                except Exception:
                    continue
        return None


# ---- scenarios ----------------------------------------------------------------------------------------------
def scenario_firefox(h: Harness) -> None:
    print('[firefox] web page with a chat textarea')
    prof = WORK / 'profiles' / 'ff'
    prof.mkdir(parents=True, exist_ok=True)
    (prof / 'user.js').write_text('\n'.join([
        'user_pref("gfx.webrender.software", true);', 'user_pref("layers.acceleration.disabled", true);',
        'user_pref("media.hardware-video-decoding.enabled", false);',
        'user_pref("browser.shell.checkDefaultBrowser", false);',
        'user_pref("datareporting.policy.dataSubmissionEnabled", false);',
        'user_pref("browser.aboutwelcome.enabled", false);',
        'user_pref("accessibility.force_disabled", -1);']))   # snap Firefox ignores the GNOME a11y switch
    subprocess.Popen(['nice', '-n', '19', 'firefox', '--no-remote', '--new-instance', '--profile', str(prof),
                      f'file://{FIX / "chat.html"}'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    h.cleanups.append(lambda: h.kill_matching(str(prof)))
    xid = h.wait(lambda: next(iter(h.windows_of(h.pids_matching(str(prof)))), None), 30)
    if not h.check('firefox window appears', xid):
        return
    pids = h.pids_matching(str(prof))
    h.wait(lambda: h.find_entry(pids, '输入框'), 15)
    h.activate(xid)
    h.check('select quote 1 (AT-SPI)', h.select_text(pids, '防止梯度爆炸的技术'))
    h.annotate(xid, 'shift+alt+q', None, '为什么不用权重衰减？')
    h.check('select quote 2 (AT-SPI)', h.select_text(pids, 'learning rate warmup'))
    h.annotate(xid, 'shift+alt+s', '1', None)
    rows = h.db()
    if h.check('two annotations stored', len(rows) == 2, str(rows)):
        a, b = rows
        h.check('ask: type/quote/comment', (a['type_id'], a['quote'], a['comment']) ==
                ('ask', '防止梯度爆炸的技术', '为什么不用权重衰减？'), str(a))
        h.check('ask: anchor captured via AT-SPI with context',
                a['anchor'].get('method') == 'atspi' and a['anchor'].get('prefix', '').endswith('是一种')
                and a['anchor'].get('suffix', '').startswith('。'), str(a['anchor']))
        h.check('ask: source window recorded', a['source'].get('xid') == xid and a['source'].get('wm_class'),
                str(a['source']))
        h.check('menu + digit 1 → expand', (b['type_id'], b['quote']) == ('expand', 'learning rate warmup'), str(b))
    panel = h.panel_xid()
    if panel:
        h.shot('firefox_panel', panel)

    expected = h.expected_fill(rows)
    QGuiApplication.clipboard().setText(ORIGINAL_CLIPBOARD, QClipboard.Clipboard)
    h.pump(0.3)
    h.key('shift+alt+Return', xid)
    entry = h.find_entry(pids, '输入框')
    got = h.wait(lambda: entry is not None and T.get_text(entry, 0, T.get_character_count(entry)), 6)
    h.check('fill: textarea receives the composed prompt', got == expected, f'got={got!r}\nexpected={expected!r}')
    h.check('fill: annotations marked sent', h.wait(lambda: all(r['status'] == 'sent' for r in h.db()), 3))
    restored = h.wait(lambda: QGuiApplication.clipboard().text(QClipboard.Clipboard) == ORIGINAL_CLIPBOARD, 4)
    h.check('fill: original clipboard restored', restored, QGuiApplication.clipboard().text()[:60])
    h.shot('firefox_after_fill', xid)


def scenario_terminal(h: Harness) -> None:
    print('[terminal] CLI agent output in gnome-terminal')
    title = f'AN_E2E_{random.randint(10000, 99999)}'
    out = h.run_dir / 'term_out.txt'
    line = '● Agent: 梯度裁剪是一种防止梯度爆炸的技术，常用 clip_grad_norm_ 实现。'
    subprocess.Popen(['gnome-terminal', '--window', '--', 'bash', '-c',
                      f'printf "\\033]0;{title}\\007"; echo; echo "{line}"; echo; cat > "{out}"'],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    xid = h.wait(lambda: h.window_titled(title), 10)
    if not h.check('terminal window appears', xid):
        return

    def close_terminal():
        for p in map(int, subprocess.run(['pgrep', '-x', 'cat'], capture_output=True, text=True).stdout.split()):
            try:
                if any(str(out) in os.readlink(f'/proc/{p}/fd/{fd}') for fd in os.listdir(f'/proc/{p}/fd')):
                    os.kill(p, 15)
            except OSError:
                pass
    h.cleanups.append(close_terminal)
    h.activate(xid)
    h.pump(0.4)
    term = None
    desk = Atspi.get_desktop(0)
    for a in (desk.get_child_at_index(i) for i in range(desk.get_child_count())):
        if a and a.get_name() == 'gnome-terminal-server':
            for node, _, _ in walk(a, time.monotonic() + 3, prune_hidden=False):
                if node.get_role_name() == 'frame' and title not in (node.get_name() or ''):
                    continue
                if node.get_role_name() == 'terminal' and node.get_state_set().contains(S.SHOWING):
                    p = node.get_parent()
                    while p is not None and p.get_role_name() != 'frame':
                        p = p.get_parent()
                    if p is not None and title in (p.get_name() or ''):
                        term = node
                        break
    if not h.check('terminal found via AT-SPI', term is not None):
        return
    quote = '防止梯度爆炸的技术'
    text = T.get_text(term, 0, T.get_character_count(term))
    i = text.find(quote)
    rects = vte_rects(term, xid, i, i + len(quote))
    if not h.check('quote located on screen', len(rects) == 1, str(rects)):
        return
    x, y, w, hh = rects[0]
    h.drag(x + 4, y + hh // 2, x + w - 4, xid)            # a real mouse selection → sets PRIMARY
    h.pump(0.3)
    h.annotate(xid, 'shift+alt+e', None, '展开讲讲阈值怎么选')
    rows = [r for r in h.db() if r['status'] == 'pending']
    h.check('terminal annotation quote', rows and rows[-1]['quote'] == quote, str(rows[-1:] if rows else rows))
    expected = h.expected_fill(rows)
    h.key('shift+alt+Return', xid)
    h.pump(1.2)
    tail = T.get_text(term, 0, T.get_character_count(term)).rstrip().splitlines()[-3:]
    print('   terminal shows after paste:', tail)
    h.key('Return', xid)
    h.key('ctrl+d', xid)
    h.wait(lambda: out.exists() and out.read_text(encoding='utf-8').strip() == expected, 4)
    got = out.read_text(encoding='utf-8').strip() if out.exists() else ''
    h.check('fill: terminal receives the composed prompt', got == expected, f'got={got!r}\nexpected={expected!r}')


def scenario_vscode(h: Harness) -> None:
    print('[vscode] markdown preview webview + Copilot Chat input')
    ud, ext = WORK / 'profiles' / 'vscode-ud', WORK / 'profiles' / 'vscode-ext'
    (ud / 'User').mkdir(parents=True, exist_ok=True)
    ext.mkdir(parents=True, exist_ok=True)
    (ud / 'User' / 'settings.json').write_text(json.dumps({
        'workbench.editorAssociations': {'*.md': 'vscode.markdown.preview.editor'},
        'workbench.startupEditor': 'none', 'security.workspace.trust.enabled': False,
        'telemetry.telemetryLevel': 'off', 'update.mode': 'none', 'window.restoreWindows': 'none'}))
    proc = subprocess.Popen(['nice', '-n', '19', '/usr/share/code/code', f'--user-data-dir={ud}',
                             f'--extensions-dir={ext}', '--disable-gpu', '--force-renderer-accessibility',
                             '--new-window', str(FIX / 'reply.md')],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    h.cleanups.append(lambda: (h.kill_matching(str(ud)), proc.terminate()))
    xid = h.wait(lambda: next(iter(h.windows_of(h.pids_matching(str(ud)) | {proc.pid})), None), 40)
    if not h.check('vscode window appears', xid):
        return
    pids = h.pids_matching(str(ud)) | {proc.pid}
    h.pump(4)
    _vscode_dismiss_dialogs(pids)
    if h.find_entry(pids, 'Chat Input') is None:
        _vscode_press(pids, 'Toggle Chat')
    chat = h.wait(lambda: h.find_entry(pids, 'Chat Input'), 15)
    if not h.check('chat input present', chat is not None):
        return
    h.activate(xid)
    h.pump(0.5)
    h.check('select quote in markdown preview', h.wait(lambda: h.select_text(pids, '让训练更加稳定'), 10))
    h.annotate(xid, 'shift+alt+w', None, '一句话即可')
    rows = [r for r in h.db() if r['status'] == 'pending']
    h.check('vscode annotation quote', rows and rows[-1]['quote'] == '让训练更加稳定', str(rows[-1:] if rows else rows))
    expected = h.expected_fill(rows)
    h.key('shift+alt+Return', xid)
    got = h.wait(lambda: T.get_text(chat, 0, T.get_character_count(chat)).strip(), 6)
    h.check('fill: chat input receives the composed prompt', got == expected, f'got={got!r}\nexpected={expected!r}')
    h.shot('vscode_after_fill', xid)


def _vscode_buttons(pids: set[int], inside_dialog: bool):
    desk = Atspi.get_desktop(0)
    for a in (desk.get_child_at_index(i) for i in range(desk.get_child_count())):
        if a is None or a.get_process_id() not in pids:
            continue
        for node, _, _ in walk(a, time.monotonic() + 3, prune_hidden=False):
            if node.get_role_name() not in ('push button', 'toggle button'):
                continue
            if inside_dialog:
                p = node.get_parent()
                while p is not None and p.get_role_name() not in ('dialog', 'alert', 'frame'):
                    p = p.get_parent()
                if p is None or p.get_role_name() == 'frame':
                    continue
            yield node


def _vscode_dismiss_dialogs(pids: set[int]) -> None:
    for _ in range(4):   # onboarding is multi-step; only ever press buttons inside a dialog
        b = next((n for n in _vscode_buttons(pids, True)
                  if (n.get_name() or '') in ('Continue without Signing In', 'Skip', 'Close', 'Done')), None)
        if b is None:
            return
        Atspi.Action.do_action(b, 0)
        time.sleep(1.2)


def _vscode_press(pids: set[int], name: str) -> None:
    b = next((n for n in _vscode_buttons(pids, False) if (n.get_name() or '').startswith(name)), None)
    if b is not None:
        Atspi.Action.do_action(b, 0)


SCENARIOS = {'firefox': scenario_firefox, 'terminal': scenario_terminal, 'vscode': scenario_vscode}


def main() -> int:
    wanted = sys.argv[1:] or list(SCENARIOS)
    h = Harness()
    print('run dir:', h.run_dir)
    try:
        h.start_app()
        for name in wanted:
            try:
                SCENARIOS[name](h)
            except Abort as e:
                h.check(f'{name}: aborted safely', False, str(e))
    finally:
        h.close()
    failed = [r for r in h.results if not r[1]]
    print(f'\n{len(h.results) - len(failed)}/{len(h.results)} checks passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
