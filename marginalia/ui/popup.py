"""The small window that pops up at the cursor to pick an annotation type and type a comment.

Two stages: 'type' (digits 1-9, 0 / arrows / Enter pick a type) and 'comment' (Enter saves, Shift+Enter newline,
Tab goes back to types). Esc or clicking elsewhere cancels.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtWidgets import (QFrame, QGridLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout,
                               QWidget)

from ..core.models import INPUT_NONE, INPUT_REQUIRED, AnnoType
from .theme import chip_style

MAX_TYPES = 12
KEYS = '1234567890'        # type i is picked with KEYS[i]; later ones with the arrows
CHIPS_PER_ROW = 4


def _elide(text: str, n: int) -> str:
    t = ' '.join(text.split())
    return t if len(t) <= n else t[:n - 1] + '…'


class AnnotatePopup(QWidget):
    submitted = Signal(str, str)   # type_id, comment
    cancelled = Signal()

    def __init__(self, activator: Callable[[int], None]):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self._activator = activator
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedWidth(460)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        frame = QFrame(objectName='popup')
        outer.addWidget(frame)
        lay = self._lay = QVBoxLayout(frame)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)
        self._source = QLabel(objectName='faint')
        self._quote = QLabel(objectName='quote')
        self._quote.setWordWrap(True)
        self._chips_box = QWidget()
        self._chips = QGridLayout(self._chips_box)
        self._chips.setContentsMargins(0, 2, 0, 2)
        self._chips.setHorizontalSpacing(6)
        self._chips.setVerticalSpacing(6)
        self._input = QPlainTextEdit()
        self._input.setFixedHeight(68)
        self._input.installEventFilter(self)
        self._error = QLabel(objectName='error')
        self._error.hide()
        self._hint = QLabel(objectName='faint')
        for w in (self._source, self._quote, self._chips_box, self._input, self._error, self._hint):
            lay.addWidget(w)
        self._types: list[AnnoType] = []
        self._buttons: list[QPushButton] = []
        self._type_id: str | None = None
        self._cursor = 0
        self._stage = 'type'
        self._has_quote = True
        self._was_active = False

    # ---- public -------------------------------------------------------------------------------------------
    def open(self, quote: str, source_label: str, types: list[AnnoType], preset: str | None, pos: QPoint) -> None:
        self._types = types[:MAX_TYPES]
        self._has_quote = bool(quote.strip())
        self._source.setText(source_label)
        self._quote.setText(f'「{_elide(quote, 140)}」' if self._has_quote
                            else '未检测到选中文本，将保存为一条独立备注（需要填写内容）')
        self._build_chips()
        self._input.clear()
        self._input.setProperty('invalid', False)
        self._error.hide()
        self._type_id = None
        self._cursor = 0
        if preset and any(t.id == preset for t in self._types + types):
            self._type_id = preset
            self._stage = 'comment'
        else:
            self._stage = 'type'
        self._refresh()
        screen = (QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()).availableGeometry()
        x = min(pos.x() + 12, screen.right() - self.width() - 8)
        y = pos.y() + 18
        if y + self.height() > screen.bottom() - 8:
            y = pos.y() - self.height() - 12
        self.move(max(screen.left() + 8, x), max(screen.top() + 8, y))
        self._was_active = False
        self.show()
        self.raise_()
        QTimer.singleShot(0, self._take_focus)

    # ---- internals ----------------------------------------------------------------------------------------
    def _take_focus(self) -> None:
        try:
            self._activator(int(self.winId()))   # mutter needs a timestamped _NET_ACTIVE_WINDOW from a background app
        except Exception:
            pass
        self.activateWindow()
        self._focus_stage()

    def _build_chips(self) -> None:
        for b in self._buttons:
            b.deleteLater()
        self._buttons = []
        for i, t in enumerate(self._types):
            b = QPushButton(f'{KEYS[i]}  {t.name}' if i < len(KEYS) else t.name)
            b.setFocusPolicy(Qt.NoFocus)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, tid=t.id: self._choose(tid))
            self._chips.addWidget(b, i // CHIPS_PER_ROW, i % CHIPS_PER_ROW)
            self._buttons.append(b)

    def _type(self) -> AnnoType | None:
        return next((t for t in self._types if t.id == self._type_id), None)

    def _refresh(self) -> None:
        for i, (t, b) in enumerate(zip(self._types, self._buttons)):
            selected = t.id == self._type_id or (self._stage == 'type' and self._type_id is None and i == self._cursor)
            b.setStyleSheet(chip_style(t.color, selected))
        t = self._type()
        comment_stage = self._stage == 'comment' and t is not None
        self._input.setVisible(comment_stage)
        if comment_stage:
            required = t.input == INPUT_REQUIRED or not self._has_quote
            self._input.setPlaceholderText(f'输入{t.name}内容…' if required else f'{t.name}：补充说明（可选）')
            self._hint.setText('Enter 保存 · Shift+Enter 换行 · Tab 换类型 · Esc 取消')
        else:
            self._hint.setText(f'按 1-{KEYS[min(len(self._types), len(KEYS)) - 1]} 或 ←→ + Enter 选择类型 · Esc 取消')
        self._fit()

    def _fit(self) -> None:
        """Shrink/grow to content; adjustSize() alone keeps the old height after hiding a child."""
        self._lay.activate()
        self.layout().activate()
        self.resize(self.width(), self.sizeHint().height())

    def _focus_stage(self) -> None:
        if self._stage == 'comment':
            self._input.setFocus()
        else:
            self.setFocus()

    def _choose(self, type_id: str) -> None:
        self._type_id = type_id
        t = self._type()
        if t and t.input == INPUT_NONE and self._has_quote:
            self._submit()
            return
        self._stage = 'comment'
        self._error.hide()
        self._refresh()
        self._focus_stage()

    def _submit(self) -> None:
        t = self._type()
        comment = self._input.toPlainText().strip()
        if t is None:
            return self._fail('请先选择批注类型')
        if not comment and (t.input == INPUT_REQUIRED or not self._has_quote):
            return self._fail(f'「{t.name}」需要填写内容')
        self.hide()
        self.submitted.emit(t.id, comment)

    def _fail(self, msg: str) -> None:
        self._error.setText(msg)
        self._error.show()
        self._input.setProperty('invalid', True)
        self._input.style().unpolish(self._input)
        self._input.style().polish(self._input)
        self._fit()

    def _cancel(self) -> None:
        if self.isVisible():
            self.hide()
            self.cancelled.emit()

    # ---- events -------------------------------------------------------------------------------------------
    def keyPressEvent(self, e: QKeyEvent) -> None:
        k = e.key()
        if k == Qt.Key_Escape:
            return self._cancel()
        if self._stage == 'type' and self._types:
            i = KEYS.find(e.text()) if e.text() else -1
            if 0 <= i < len(self._types):
                return self._choose(self._types[i].id)
            if k in (Qt.Key_Right, Qt.Key_Down, Qt.Key_Tab):
                self._cursor = (self._cursor + 1) % len(self._types)
                return self._refresh()
            if k in (Qt.Key_Left, Qt.Key_Up, Qt.Key_Backtab):
                self._cursor = (self._cursor - 1) % len(self._types)
                return self._refresh()
            if k in (Qt.Key_Return, Qt.Key_Enter):
                return self._choose(self._types[self._cursor].id)
        super().keyPressEvent(e)

    def eventFilter(self, obj, e) -> bool:
        if obj is self._input and e.type() == QEvent.KeyPress:
            k = e.key()
            if k in (Qt.Key_Return, Qt.Key_Enter) and not (e.modifiers() & Qt.ShiftModifier):
                self._submit()
                return True
            if k == Qt.Key_Escape:
                self._cancel()
                return True
            if k in (Qt.Key_Tab, Qt.Key_Backtab):
                self._stage = 'type'
                self._cursor = max(0, next((i for i, t in enumerate(self._types) if t.id == self._type_id), 0))
                self._type_id = None
                self._refresh()
                self._focus_stage()
                return True
        return super().eventFilter(obj, e)

    def changeEvent(self, e) -> None:
        if e.type() == QEvent.ActivationChange:
            if self.isActiveWindow():
                self._was_active = True
            elif self._was_active and self.isVisible():
                QTimer.singleShot(150, lambda: None if self.isActiveWindow() else self._cancel())
        super().changeEvent(e)
