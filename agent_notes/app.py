"""Controller: hotkey -> capture -> popup -> store -> panel, and panel/hotkey -> compose -> fill."""
from __future__ import annotations

import logging
import os
import sys

from PySide6.QtCore import QMimeData, QObject, QTimer, QUrl, QFileSystemWatcher
from PySide6.QtGui import QClipboard, QCursor, QDesktopServices, QGuiApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from . import config as cfgmod
from .core.composer import compose
from .core.models import INPUT_NONE, SENT, Annotation
from .core.store import Store
from .platform.base import WindowInfo, get_platform
from .ui import theme
from .ui.panel import FloatingPanel, source_label
from .ui.popup import AnnotatePopup
from .ui.toast import Toast
from .ui.tray import app_icon, make_tray
from .worker import Worker

log = logging.getLogger('agent_notes')
RESTORE_CLIPBOARD_MS = 900


def _copy_mime(md: QMimeData | None) -> QMimeData:
    out = QMimeData()
    if md is not None:
        for f in md.formats():
            out.setData(f, md.data(f))
    return out


class Controller(QObject):
    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.platform = get_platform()
        self.worker = Worker()
        self.state = cfgmod.load_state()
        self.cfg, cfg_error = cfgmod.Config.load()
        self.store = Store(cfgmod.data_dir() / 'notes.db')
        self.toast = Toast()
        self.panel = FloatingPanel(self)
        self.popup = AnnotatePopup(self.platform.activate)
        self.popup.setWindowOpacity(self._popup_opacity())
        self.popup.submitted.connect(self._on_popup_submitted)
        self.popup.cancelled.connect(self._on_popup_cancelled)
        if not self.state.get('order_newest_first'):     # one-time: older versions listed oldest first
            self.store.sort_newest_first()
            self.state['order_newest_first'] = True
            self.save_state()
        self.store.subscribe(self.panel.refresh)
        self._capture_ctx: dict | None = None
        self._busy = False
        self._last_external: WindowInfo | None = None

        self.hotkeys = self.platform.hotkey_listener()
        self.hotkeys.triggered.connect(self.on_hotkey)
        self.hotkeys.failed.connect(lambda spec, why: self.toast.show_message(f'快捷键 {spec} 无法注册：{why}', 'warn', 4000))
        self.hotkeys.start(self.cfg.hotkey_bindings())

        self._watcher = QFileSystemWatcher([str(cfgmod.config_path()), str(cfgmod.config_dir())])
        self._reload_timer = QTimer(self, singleShot=True, interval=400, timeout=self.reload_config)
        self._watcher.fileChanged.connect(lambda *_: self._reload_timer.start())
        self._watcher.directoryChanged.connect(lambda *_: self._reload_timer.start())

        self.tray = make_tray(self)
        self.panel.refresh()
        self.panel.show_panel()
        if cfg_error:
            self.toast.show_message(cfg_error, 'error', 6000)
        elif not self.platform.accessibility_enabled():
            self.toast.show_message('系统无障碍未开启：无法精确定位选区和输入框。\n'
                                    'gsettings set org.gnome.desktop.interface toolkit-accessibility true', 'warn', 8000)

    # ---- hotkeys --------------------------------------------------------------------------------------------
    def on_hotkey(self, action: str) -> None:
        log.info('hotkey %s', action)
        if action == 'menu':
            self.begin_capture(None)
        elif action.startswith('type:'):
            self.begin_capture(action[5:])
        elif action in ('fill', 'fill_plain'):
            win = self.platform.active_window()
            if win and win.pid != os.getpid():
                self._last_external = win
            self.fill(plain=action == 'fill_plain')
        elif action == 'toggle_panel':
            self.panel.toggle()

    # ---- capture ----------------------------------------------------------------------------------------------
    def begin_capture(self, type_id: str | None) -> None:
        if self._busy or self.popup.isVisible():
            return
        win = self.platform.active_window()
        if win is None or win.pid == os.getpid():
            self.toast.show_message('请先在 Agent 窗口中选中文字，再按快捷键', 'warn')
            return
        self._last_external = win
        # PRIMARY keeps the last selection made anywhere; only trust it if this app made it.
        primary = (QGuiApplication.clipboard().text(QClipboard.Selection)
                   if self.platform.selection_belongs_to(win) else '')
        self._busy = True
        self.worker.submit(self.platform.capture_selection, win, primary,
                           cb=lambda res: self._on_captured(win, primary, type_id, res))

    def _on_captured(self, win: WindowInfo, primary: str, type_id: str | None, res) -> None:
        self._busy = False
        if isinstance(res, Exception) or not res:
            res = None
        anchor = dict(res) if res else {'method': 'primary' if primary.strip() else 'none'}
        quote = anchor.pop('quote', '') or primary.strip()
        source = {'xid': win.xid, 'pid': win.pid, 'wm_class': win.wm_class, 'title': win.title,
                  'app': anchor.pop('app', ''), 'url': anchor.pop('url', '')}
        log.info('captured via %s: %r from %s', anchor.get('method'), quote[:60], win.wm_class)
        t = self.cfg.type_map.get(type_id) if type_id else None
        self._capture_ctx = {'win': win, 'quote': quote, 'anchor': anchor, 'source': source}
        if t is not None and t.input == INPUT_NONE and quote:
            self._on_popup_submitted(t.id, '')
            return
        self.popup.open(quote, source_label(source, 60), self.cfg.types, type_id, QCursor.pos())

    def _on_popup_submitted(self, type_id: str, comment: str) -> None:
        ctx, self._capture_ctx = self._capture_ctx, None
        if ctx is None:
            return
        self.store.add(Annotation(type_id=type_id, quote=ctx['quote'], comment=comment,
                                  anchor=ctx['anchor'], source=ctx['source']))
        name = self.cfg.type_map[type_id].name if type_id in self.cfg.type_map else type_id
        self.panel.reveal()
        self.toast.show_message(f'已添加批注 · {name}', 'ok', 1400, near=self.panel)
        self.worker.submit(self.platform.activate, ctx['win'].xid)   # hand focus back to where the user was

    def _on_popup_cancelled(self) -> None:
        ctx, self._capture_ctx = self._capture_ctx, None
        if ctx is not None:
            self.worker.submit(self.platform.activate, ctx['win'].xid)

    # ---- compose & fill -----------------------------------------------------------------------------------------
    def compose(self, items: list[Annotation], plain: bool = False) -> str:
        return compose(items, self.cfg.type_map, self.cfg.prompt, plain)

    def _resolve_target(self, items: list[Annotation]) -> WindowInfo | None:
        if self.cfg.fill.get('target', 'source') == 'source':
            latest = max(items, key=lambda a: a.created_at)
            s = latest.source
            if s.get('xid') and self.platform.window_exists(s['xid']):
                return WindowInfo(xid=s['xid'], pid=s.get('pid'), wm_instance=s.get('wm_class', ''),
                                  wm_class=s.get('wm_class', ''), title=s.get('title', ''))
        return self._last_external

    def fill(self, plain: bool = False) -> None:
        """plain=True: only quotes + comments, without the header and per-type instructions."""
        if self._busy:
            return
        items = self.panel.prompt_items()
        if not items:
            self.toast.show_message('没有勾选的待发送批注', 'warn', near=self.panel)
            return
        text = self.compose(items, plain)
        cb = QGuiApplication.clipboard()
        target = self._resolve_target(items) if self.cfg.fill.get('mode', 'fill') == 'fill' else None
        if target is None:
            cb.setText(text, QClipboard.Clipboard)
            self._mark_sent(items)
            self.toast.show_message(f'已复制 {len(items)} 条批注到剪贴板', 'ok', near=self.panel)
            return
        terminal = self.platform.is_terminal(target)
        saved = {QClipboard.Clipboard: _copy_mime(cb.mimeData(QClipboard.Clipboard))}
        cb.setText(text, QClipboard.Clipboard)
        if terminal:   # terminals paste PRIMARY on Shift+Insert
            saved[QClipboard.Selection] = _copy_mime(cb.mimeData(QClipboard.Selection))
            cb.setText(text, QClipboard.Selection)
        latest = max(items, key=lambda a: a.created_at)
        self._busy = True
        self.worker.submit(self.platform.inject, target, terminal, latest.anchor.get('path'),
                           bool(self.cfg.fill.get('auto_send')),
                           cb=lambda res: self._on_injected(res, items, saved))

    def _on_injected(self, res, items: list[Annotation], saved: dict) -> None:
        self._busy = False
        if isinstance(res, dict) and res.get('ok'):
            def restore():
                for mode, md in saved.items():
                    QGuiApplication.clipboard().setMimeData(md, mode)
            QTimer.singleShot(RESTORE_CLIPBOARD_MS, restore)
            self._mark_sent(items)
            self.toast.show_message(f'已填入 {len(items)} 条批注', 'ok', 1600)
            log.info('filled %d items, input=%r', len(items), res.get('input'))
        else:
            why = res.get('reason') if isinstance(res, dict) else repr(res)
            log.warning('fill failed: %s', why)
            self.toast.show_message('未能切换到目标窗口，内容已复制到剪贴板，可手动粘贴', 'warn', 3500)

    def _mark_sent(self, items: list[Annotation]) -> None:
        if self.cfg.fill.get('mark_sent', True):
            self.store.set_status([a.id for a in items], SENT, checked=False)

    # ---- misc -----------------------------------------------------------------------------------------------
    def goto_source(self, a: Annotation) -> None:
        xid = a.source.get('xid')
        if xid and self.platform.window_exists(xid):
            self.worker.submit(self.platform.activate, xid)
        else:
            self.toast.show_message('来源窗口已关闭', 'warn', near=self.panel)

    def open_config(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(cfgmod.config_path())))

    def reload_config(self) -> None:
        path = str(cfgmod.config_path())
        if path not in self._watcher.files() and os.path.exists(path):
            self._watcher.addPath(path)   # editors that replace the file drop the watch
        cfg, err = cfgmod.Config.load()
        if err:
            self.toast.show_message(err, 'error', 6000)
            return
        if cfg.data == self.cfg.data:
            return
        self.cfg = cfg
        self.hotkeys.start(cfg.hotkey_bindings())
        self.panel.config_changed()
        self.popup.setWindowOpacity(self._popup_opacity())
        self.panel.refresh()
        self.toast.show_message('配置已重新加载', 'ok', 1400, near=self.panel)

    def _popup_opacity(self) -> float:
        return min(1.0, max(0.3, float(self.cfg.data.get('popup', {}).get('opacity', 0.9))))

    def save_state(self) -> None:
        cfgmod.save_state(self.state)

    def show_from_second_instance(self) -> None:
        self.panel.show_panel()

    def quit(self) -> None:
        self.hotkeys.stop()
        self.worker.shutdown()
        self.app.quit()


def _setup_logging() -> None:
    fmt = '%(asctime)s %(levelname)s %(name)s: %(message)s'
    handlers = [logging.FileHandler(cfgmod.data_dir() / 'agent-notes.log', encoding='utf-8'),
                logging.StreamHandler(sys.stderr)]
    logging.basicConfig(level=logging.INFO, format=fmt, handlers=handlers)


def run(argv: list[str]) -> int:
    _setup_logging()
    app = QApplication(argv)
    app.setApplicationName('agent-notes')
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(app_icon())
    theme.apply(app)

    server_name = f'agent-notes-{os.getuid()}'
    sock = QLocalSocket()
    sock.connectToServer(server_name)
    if sock.waitForConnected(300):     # already running: just show its panel
        sock.write(b'show')
        sock.waitForBytesWritten(300)
        return 0
    QLocalServer.removeServer(server_name)
    server = QLocalServer()
    server.listen(server_name)

    ctl = Controller(app)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), ctl.show_from_second_instance()))
    log.info('agent-notes started')
    return app.exec()
