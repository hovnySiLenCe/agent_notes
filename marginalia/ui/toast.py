"""Transient, non-focusable notification bubble."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .theme import C, add_shadow, margin

_KIND_COLOR = {'info': C['accent'], 'ok': C['ok'], 'warn': C['warn'], 'error': C['danger']}


class Toast(QWidget):
    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.X11BypassWindowManagerHint | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(margin(), margin(), margin(), margin())
        self._frame = QFrame(objectName='toast')
        add_shadow(self._frame)
        inner = QHBoxLayout(self._frame)
        inner.setContentsMargins(12, 9, 14, 9)
        inner.setSpacing(9)
        self._dot = QLabel()
        self._dot.setFixedSize(8, 8)
        inner.addWidget(self._dot, 0, Qt.AlignTop)
        self._label = QLabel()
        self._label.setWordWrap(True)
        self._label.setMaximumWidth(420)
        inner.addWidget(self._label)
        lay.addWidget(self._frame)
        self._timer = QTimer(self, singleShot=True, timeout=self.hide)

    def show_message(self, text: str, kind: str = 'info', ms: int = 2200, near: QWidget | None = None) -> None:
        self._dot.setStyleSheet(f'background: {_KIND_COLOR.get(kind, C["accent"])}; border-radius: 4px;'
                                f' margin-top: 6px;')
        self._dot.setFixedSize(8, 14)
        self._label.setText(text)
        self.adjustSize()
        if near is not None and near.isVisible():
            g = near.frameGeometry()
            x, y = g.center().x() - self.width() // 2, g.bottom() + 8
            screen = near.screen().availableGeometry()
            if y + self.height() > screen.bottom():
                y = g.top() - self.height() - 8
        else:
            screen = (QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()).availableGeometry()
            x, y = screen.center().x() - self.width() // 2, screen.bottom() - self.height() - 48
        self.move(max(screen.left() + 8, min(x, screen.right() - self.width() - 8)), y)
        self.show()
        self.raise_()
        self._timer.start(ms)
