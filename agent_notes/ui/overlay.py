"""Click-through, always-on-top layer that paints highlights over annotated text in other applications.

The window only spans the highlights' bounding box and is shaped (X Shape mask) to the highlights themselves,
so the compositor never blends a full-screen transparent surface and clicks always reach the app below.
Without a compositor translucency is impossible (the window would hide the text), so only underlines are drawn.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QRegion
from PySide6.QtWidgets import QWidget

PAD = 3                 # px around each text line


@dataclass(frozen=True)
class Mark:
    rects: tuple[QRect, ...]     # text-line rectangles, global logical coordinates
    color: str
    focus: bool = False          # hovered / jumped-to annotation: drawn stronger


class HighlightOverlay(QWidget):
    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.X11BypassWindowManagerHint | Qt.WindowTransparentForInput
                         | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setWindowTitle('Agent Notes highlights')
        self._marks: tuple[Mark, ...] = ()
        self.translucent = True            # False: no compositing manager, underline only

    @staticmethod
    def _underline(g: QRect, focus: bool) -> QRect:
        h = 3 if focus else 2
        return QRect(g.left(), g.bottom() - h + 1, g.width(), h)

    def _box(self, r: QRect) -> QRect:
        g = r.adjusted(-2, -1, 2, 1)
        return g if self.translucent else self._underline(g.adjusted(0, 0, 0, 2), True)

    @property
    def marks(self) -> tuple[Mark, ...]:
        return self._marks

    def set_marks(self, marks: list[Mark]) -> None:
        marks = tuple(m for m in marks if m.rects)
        if marks == self._marks:
            return
        self._marks = marks
        if not marks:
            self.hide()
            return
        box = QRect()
        shape = QRegion()
        for m in marks:
            for r in m.rects:
                g = r.adjusted(-PAD, -PAD, PAD, PAD)
                box = box.united(g)
                shape = shape.united(QRegion(self._box(r)))
        self.setGeometry(box)
        self.setMask(shape.translated(-box.topLeft()))
        if not self.isVisible():
            self.show()
        self.raise_()                 # stay above windows mapped since (override-redirect isn't restacked)
        self.update()

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        origin = self.geometry().topLeft()
        for m in sorted(self._marks, key=lambda m: m.focus):      # focused mark on top
            c = QColor(m.color)
            fill = QColor(c)
            fill.setAlpha(110 if m.focus else 55)
            for r in m.rects:
                g = r.translated(-origin).adjusted(-2, -1, 2, 1)
                if not self.translucent:
                    p.fillRect(self._underline(g.adjusted(0, 0, 0, 2), True), c)
                    continue
                p.setPen(Qt.NoPen)
                p.setBrush(fill)
                p.drawRoundedRect(g, 3, 3)
                p.fillRect(self._underline(g, m.focus), c)
                if m.focus:
                    p.setPen(QPen(c, 1.5))
                    p.setBrush(Qt.NoBrush)
                    p.drawRoundedRect(g.adjusted(-1, -1, 1, 1), 3, 3)
