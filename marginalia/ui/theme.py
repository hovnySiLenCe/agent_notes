"""Colors and the app-wide stylesheet (one dark theme for now)."""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QGraphicsDropShadowEffect, QWidget

C = {
    'bg': 'rgba(23, 24, 29, 250)',
    'bg_solid': '#17181D',
    'surface': '#202128',
    'surface_hover': '#282A32',
    'raised': '#2E3039',
    'border': '#2F313A',
    'border_strong': '#3D404B',
    'text': '#ECECF1',
    'muted': '#A4A6B0',
    'faint': '#6E717C',
    'check_base': '#3D3F49',
    'accent': '#5B8DEF',
    'accent_hover': '#7AA3F3',
    'danger': '#E5484D',
    'ok': '#3FB27F',
    'warn': '#F5A623',
}
SHADOW = 10          # px around floating windows for their drop shadow (with a compositor only)
_composited = True

STYLE = """
QWidget { color: %(text)s; font-size: 13px; }
QToolTip { background: %(raised)s; color: %(text)s; border: 1px solid %(border_strong)s; border-radius: 6px;
           padding: 4px 8px; }
QFrame#panel, QFrame#popup { background: %(bg)s; border: 1px solid %(border)s; border-radius: 12px; }
QFrame#toast { background: %(bg)s; border: 1px solid %(border)s; border-radius: 10px; }
QFrame#bubble { background: %(bg)s; border: 1px solid %(border_strong)s; border-radius: 15px; }
QToolButton#bubbleButton { padding: 3px 9px; border-radius: 11px; font-weight: 600; font-size: 12px; }
QToolButton#bubbleButton:hover { background: %(surface_hover)s; }
QFrame#card { background: %(surface)s; border: 1px solid %(border)s; border-radius: 9px; }
QFrame#card:hover { background: %(surface_hover)s; border-color: %(border_strong)s; }
QFrame#card[sent="true"] QLabel#quote { color: %(faint)s; }
QFrame#card[sent="true"] QLabel#comment { color: %(muted)s; }
QLabel#title { font-weight: 700; font-size: 14px; }
QLabel#countPill { color: %(accent)s; background: rgba(91, 141, 239, 36); border-radius: 8px; padding: 0 7px;
                   font-size: 11px; font-weight: 600; }
QLabel#muted { color: %(muted)s; }
QLabel#faint { color: %(faint)s; font-size: 12px; }
QLabel#quote { color: %(muted)s; }
QLabel#popupQuote { color: %(text)s; }
QLabel#comment { color: %(text)s; }
QLabel#badge { color: %(faint)s; font-size: 11px; border: 1px solid %(border_strong)s; border-radius: 4px;
               padding: 0 5px; }
QLabel#badgeDone { color: %(ok)s; font-size: 11px; border: 1px solid %(ok)s; border-radius: 4px; padding: 0 5px; }
QLabel#error { color: %(danger)s; font-size: 12px; }
QLabel#empty { color: %(faint)s; padding: 4px 12px 24px 12px; line-height: 150%%; }
QLabel#hint { color: %(faint)s; font-size: 12px; }
QPushButton { background: transparent; border: 1px solid %(border_strong)s; border-radius: 7px; padding: 6px 12px; }
QPushButton:hover { background: %(surface_hover)s; }
QPushButton:checked { background: %(surface_hover)s; border-color: %(accent)s; color: %(accent)s; }
QPushButton:disabled { color: %(faint)s; border-color: %(border)s; }
QPushButton#primary { background: %(accent)s; border-color: %(accent)s; color: white; font-weight: 600; }
QPushButton#primary:hover { background: %(accent_hover)s; border-color: %(accent_hover)s; }
QPushButton#primary:disabled { background: %(surface)s; border-color: %(border)s; color: %(faint)s; font-weight: 400; }
QToolButton { background: transparent; border: none; border-radius: 6px; padding: 4px; color: %(muted)s; }
QToolButton:hover { background: %(surface_hover)s; color: %(text)s; }
QToolButton:checked { color: %(accent)s; background: rgba(91, 141, 239, 36); }
QToolButton::menu-indicator { image: none; width: 0; }
QToolButton#segment { padding: 2px 9px; font-size: 12px; }
QToolButton#cardDelete, QToolButton#cardAction { padding: 2px; border-radius: 5px; }
QToolButton#cardDelete:hover { background: rgba(229, 72, 77, 40); }
QToolButton#cardAction:hover { background: %(raised)s; }
QLabel#locState { color: %(faint)s; font-size: 11px; }
QLabel#locState[state="ok"] { color: %(accent)s; }
QLabel#locState[state="missing"] { color: %(warn)s; }
QComboBox { background: %(surface)s; border: 1px solid %(border)s; border-radius: 7px; padding: 4px 10px;
            color: %(muted)s; }
QComboBox:hover { border-color: %(border_strong)s; color: %(text)s; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow { image: url(%(chevron)s); width: 12px; height: 12px; }
QComboBox QAbstractItemView { background: %(bg_solid)s; border: 1px solid %(border_strong)s; border-radius: 6px;
                              padding: 4px; selection-background-color: %(surface_hover)s; outline: none; }
QPlainTextEdit { background: %(surface)s; border: 1px solid %(border)s; border-radius: 8px; padding: 6px 8px;
                 selection-background-color: %(accent)s; }
QPlainTextEdit:focus { border-color: %(accent)s; }
QPlainTextEdit[invalid="true"] { border-color: %(danger)s; }
QCheckBox { spacing: 0; }
QCheckBox::indicator { width: 15px; height: 15px; border: 1.5px solid %(border_strong)s; border-radius: 4px;
                       background: %(bg_solid)s; }
QCheckBox::indicator:hover { border-color: %(accent)s; }
QCheckBox::indicator:checked { background: %(accent)s; border-color: %(accent)s; image: url(%(check)s); }
QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }
QScrollBar:vertical { width: 8px; background: transparent; margin: 2px; }
QScrollBar::handle:vertical { background: %(border_strong)s; border-radius: 3px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QMenu { background: %(bg_solid)s; border: 1px solid %(border_strong)s; border-radius: 8px; padding: 5px; }
QMenu::item { padding: 6px 22px 6px 14px; border-radius: 5px; }
QMenu::item:selected { background: %(surface_hover)s; }
QMenu::item:disabled { color: %(faint)s; }
QMenu::separator { height: 1px; background: %(border)s; margin: 4px 8px; }
QMenu::indicator { width: 14px; height: 14px; left: 4px; }
QDialog, QMessageBox { background: %(bg_solid)s; }
"""


def _icon_files() -> dict:
    from .. import config as cfgmod
    from .icons import write_svg
    folder = cfgmod.data_dir() / 'icons'
    return {'check': write_svg('check', '#FFFFFF', folder).as_posix(),
            'chevron': write_svg('chevron', C['muted'], folder).as_posix()}


def apply(app: QApplication, composited: bool = True) -> None:
    """composited: a compositing manager runs (else translucent margins would show black: no shadows)."""
    global _composited
    _composited = composited
    app.setStyle('Fusion')
    pal = QPalette()
    for role, color in ((QPalette.Window, C['bg_solid']), (QPalette.Base, C['surface']),
                        (QPalette.AlternateBase, C['surface_hover']), (QPalette.Button, C['surface']),
                        (QPalette.Text, C['text']), (QPalette.WindowText, C['text']),
                        (QPalette.ButtonText, C['text']), (QPalette.Highlight, C['accent']),
                        (QPalette.HighlightedText, '#FFFFFF'), (QPalette.ToolTipBase, C['raised']),
                        (QPalette.ToolTipText, C['text']), (QPalette.PlaceholderText, C['faint'])):
        pal.setColor(role, QColor(color))
    app.setPalette(pal)
    app.setStyleSheet(STYLE % dict(C, **_icon_files()))


def rgba(color: str, alpha: int) -> str:
    c = QColor(color)
    return f'rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})'


def margin() -> int:
    """Transparent margin floating windows keep around their frame for the shadow."""
    return SHADOW if _composited else 0


def add_shadow(frame: QWidget) -> None:
    """Soft drop shadow (the window needs margin() px of transparent margin around the frame)."""
    if not _composited:
        return
    fx = QGraphicsDropShadowEffect(frame)
    fx.setBlurRadius(SHADOW * 2)
    fx.setOffset(0, 2)
    fx.setColor(QColor(0, 0, 0, 120))
    frame.setGraphicsEffect(fx)


def quote_block(label: QWidget, color: str) -> QWidget:
    """The quote with a thin colored bar on its left."""
    from PySide6.QtWidgets import QFrame, QHBoxLayout
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(9)
    bar = QFrame()
    bar.setFixedWidth(2)
    bar.setStyleSheet(f'background: {color}; border-radius: 1px;')
    lay.addWidget(bar)
    lay.addWidget(label, 1)
    return box


def type_tag_style(color: str) -> str:
    """The small colored label naming an annotation's type."""
    return (f'color: {color}; background: {rgba(color, 38)}; border-radius: 4px; padding: 0 6px;'
            f' font-weight: 600; font-size: 12px;')


def chip_style(color: str, selected: bool) -> str:
    """A type button in the annotation popup (QPushButton#chip with labels #chipKey / #chipName inside)."""
    bg = rgba(color, 230) if selected else rgba(color, 24)
    hover = rgba(color, 245) if selected else rgba(color, 56)
    border = color if selected else rgba(color, 110)
    name = '#FFFFFF' if selected else color
    key = 'rgba(255, 255, 255, 190)' if selected else rgba(color, 150)
    return (f'QPushButton#chip {{ background: {bg}; border: 1px solid {border}; border-radius: 8px;'
            f' padding: 0; min-height: 30px; }}'
            f'QPushButton#chip:hover {{ background: {hover}; }}'
            f'QLabel#chipName {{ color: {name}; font-weight: 600; background: transparent; }}'
            f'QLabel#chipKey {{ color: {key}; font-size: 11px; background: transparent; }}')
