"""System tray icon (StatusNotifier / XEmbed, whichever the desktop offers)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .theme import C

if TYPE_CHECKING:
    from ..app import Controller


def app_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(C['accent']))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(4, 4, 56, 56, 14, 14)
    f = QFont()
    f.setPixelSize(34)
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor('#FFFFFF'))
    p.drawText(QRect(4, 2, 56, 56), Qt.AlignCenter, '注')
    p.end()
    return QIcon(pm)


def make_tray(ctl: 'Controller') -> QSystemTrayIcon | None:
    if not QSystemTrayIcon.isSystemTrayAvailable():
        return None
    tray = QSystemTrayIcon(app_icon())
    tray.setToolTip('Marginalia')
    menu = QMenu()
    menu.addAction('显示 / 隐藏面板', ctl.panel.toggle)
    menu.addAction('打开配置文件', ctl.open_config)
    menu.addAction('重新加载配置', ctl.reload_config)
    menu.addSeparator()
    menu.addAction('退出', ctl.quit)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: ctl.panel.toggle() if reason == QSystemTrayIcon.Trigger else None)
    tray._menu = menu   # keep a reference
    tray.show()
    return tray
