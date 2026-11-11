"""Small monochrome line icons (24x24 SVG paths), drawn in the theme's colors.

Emoji (🗑 📌) render in color and in a different style on every system; these match the rest of the UI.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_SHAPES = {
    'trash': '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>',
    'pin': '<path d="M12 16v6M8.5 3h7l-1 6.5L18 13v1.5H6V13l3.5-3.5z"/>',
    'more': '<circle cx="5" cy="12" r="1.6" fill="{c}"/><circle cx="12" cy="12" r="1.6" fill="{c}"/>'
            '<circle cx="19" cy="12" r="1.6" fill="{c}"/>',
    'close': '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
    'target': '<circle cx="12" cy="12" r="6.5"/><circle cx="12" cy="12" r="1.5" fill="{c}"/>'
              '<path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3"/>',
    'check': '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    'undo': '<path d="M9 14L4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
    'note': '<path d="M5 4h10l4 4v12H5z"/><path d="M15 4v4h4M8.5 12.5h7M8.5 16h5"/>',
    'chevron': '<path d="M6 9.5l6 6 6-6"/>',
}


def _svg(name: str, color: str, stroke: float = 2.0) -> bytes:
    body = _SHAPES[name].replace('{c}', color)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>').encode()


@lru_cache(maxsize=128)
def pixmap(name: str, color: str, size: int = 16) -> QPixmap:
    app = QGuiApplication.instance()
    dpr = app.devicePixelRatio() if app else 1.0
    pm = QPixmap(round(size * dpr), round(size * dpr))
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    QSvgRenderer(QByteArray(_svg(name, color))).render(p, QRectF(0, 0, pm.width(), pm.height()))
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name: str, color: str, hover: str | None = None, size: int = 16) -> QIcon:
    ic = QIcon(pixmap(name, color, size))
    if hover:
        ic.addPixmap(pixmap(name, hover, size), QIcon.Active)
        ic.addPixmap(pixmap(name, hover, size), QIcon.Selected)
    return ic


def write_svg(name: str, color: str, folder: Path) -> Path:
    """The icon as a file, for stylesheets (QCheckBox::indicator { image: url(...) })."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f'{name}-{color.lstrip("#")}.svg'
    if not path.exists():
        path.write_bytes(_svg(name, color, 3.0))
    return path
