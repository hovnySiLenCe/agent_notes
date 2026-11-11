"""Small row of annotation-type buttons shown next to the pointer right after text is selected with the mouse.

It never takes the keyboard focus: clicking it leaves the source window active and its selection intact,
so the normal capture path (the same as pressing the type's hotkey) reads the selection afterwards.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QToolButton, QVBoxLayout, QWidget

from ..core.models import AnnoType
from .icons import icon
from .theme import C, add_shadow, margin


def _dot(color: str, size: int = 8) -> QIcon:
    dpr = QGuiApplication.instance().devicePixelRatio() if QGuiApplication.instance() else 1.0
    pm = QPixmap(round(size * dpr), round(size * dpr))
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(0, 0, pm.width(), pm.height())
    p.end()
    pm.setDevicePixelRatio(dpr)
    return QIcon(pm)


class SelectionBubble(QWidget):
    chosen = Signal(str)          # type id; '' = open the full annotation menu

    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.X11BypassWindowManagerHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowTitle('Marginalia bubble')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(margin(), margin(), margin(), margin())
        self._frame = QFrame(objectName='bubble')
        add_shadow(self._frame)
        self._row = QHBoxLayout(self._frame)
        self._row.setContentsMargins(4, 4, 4, 4)
        self._row.setSpacing(1)
        lay.addWidget(self._frame)
        self._timer = QTimer(self, singleShot=True, timeout=self.hide)
        self.timeout_ms = 3500
        self._types: list[tuple] = []

    def set_types(self, types: list[AnnoType], hotkeys: dict[str, str]) -> None:
        key = [(t.id, t.name, t.color) for t in types]
        if key == self._types:
            return
        self._types = key
        while self._row.count():
            w = self._row.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        for t in types:
            tip = f'添加「{t.name}」批注' + (f'（{hotkeys[t.id]}）' if hotkeys.get(t.id) else '')
            self._row.addWidget(self._button(t.name, tip, t.id, t.color))
        more = self._button('', '批注菜单：选类型、写说明' + (f'（{hotkeys[""]}）' if hotkeys.get('') else ''),
                            '', C['muted'])
        more.setIcon(icon('more', C['muted'], C['text']))
        more.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self._row.addWidget(more)
        self.adjustSize()

    def _button(self, text: str, tip: str, type_id: str, color: str) -> QToolButton:
        b = QToolButton(objectName='bubbleButton')
        b.setText(text)
        b.setToolTip(tip)
        b.setCursor(Qt.PointingHandCursor)
        b.setFocusPolicy(Qt.NoFocus)
        if text:
            b.setIcon(_dot(color))
            b.setIconSize(QSize(8, 8))
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        b.setStyleSheet(f'QToolButton#bubbleButton {{ color: {C["text"]}; }}')
        b.clicked.connect(lambda: self._choose(type_id))
        return b

    def _choose(self, type_id: str) -> None:
        self.hide()
        self.chosen.emit(type_id)

    def show_at(self, pos: QPoint | None = None) -> None:
        pos = QCursor.pos() if pos is None else pos
        self.adjustSize()
        screen = (QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()).availableGeometry()
        x, y = pos.x() + 10 - margin(), pos.y() + 18 - margin()
        if y + self.height() > screen.bottom():
            y = pos.y() - self.height() - 12
        self.move(max(screen.left() + 4, min(x, screen.right() - self.width() - 4)), y)
        self.show()
        self.raise_()
        self._timer.start(self.timeout_ms)

    def contains_pointer(self) -> bool:
        return self.isVisible() and self.frameGeometry().contains(QCursor.pos())

    def enterEvent(self, e) -> None:
        self._timer.stop()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self._timer.start(1200)
        super().leaveEvent(e)
