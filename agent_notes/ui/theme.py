"""Colors and the app-wide stylesheet (one dark theme for now)."""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

C = {
    'bg': 'rgba(27, 28, 33, 247)',
    'bg_solid': '#1B1C21',
    'surface': '#24252B',
    'surface_hover': '#2C2D35',
    'border': '#363740',
    'text': '#E8E8EC',
    'muted': '#A0A2AB',
    'faint': '#6F717B',
    'check_base': '#3D3F49',
    'accent': '#4C8BF5',
    'accent_hover': '#6A9EF7',
    'danger': '#E5484D',
    'ok': '#3FB27F',
}

STYLE = """
QWidget { color: %(text)s; font-size: 13px; }
QFrame#panel, QFrame#popup { background: %(bg)s; border: 1px solid %(border)s; border-radius: 10px; }
QFrame#toast { background: %(bg)s; border: 1px solid %(border)s; border-radius: 8px; }
QFrame#bubble { background: %(bg)s; border: 1px solid %(border)s; border-radius: 8px; }
QToolButton#bubbleButton { padding: 2px 8px; font-weight: 600; }
QFrame#card { background: %(surface)s; border: 1px solid %(border)s; border-radius: 8px; }
QFrame#card:hover { background: %(surface_hover)s; }
QFrame#card[sent="true"] QLabel#quote { color: %(faint)s; }
QFrame#card[sent="true"] QLabel#comment { color: %(muted)s; }
QLabel#title { font-weight: 600; font-size: 14px; }
QLabel#muted { color: %(muted)s; }
QLabel#faint { color: %(faint)s; font-size: 12px; }
QLabel#quote { color: %(muted)s; }
QLabel#badge { color: %(faint)s; font-size: 11px; border: 1px solid %(border)s; border-radius: 4px; padding: 0 4px; }
QLabel#badgeDone { color: %(ok)s; font-size: 11px; border: 1px solid %(ok)s; border-radius: 4px; padding: 0 4px; }
QLabel#error { color: %(danger)s; font-size: 12px; }
QLabel#empty { color: %(faint)s; padding: 24px 12px; }
QPushButton { background: %(surface)s; border: 1px solid %(border)s; border-radius: 6px; padding: 5px 12px; }
QPushButton:hover { background: %(surface_hover)s; }
QPushButton:disabled { color: %(faint)s; }
QPushButton#primary { background: %(accent)s; border-color: %(accent)s; color: white; font-weight: 600; }
QPushButton#primary:hover { background: %(accent_hover)s; }
QPushButton#primary:disabled { background: %(surface)s; border-color: %(border)s; color: %(faint)s; font-weight: 400; }
QToolButton { background: transparent; border: none; border-radius: 5px; padding: 3px 7px; color: %(muted)s; }
QToolButton:hover { background: %(surface_hover)s; color: %(text)s; }
QToolButton:checked { color: %(accent)s; background: %(surface_hover)s; }
QToolButton::menu-indicator { image: none; width: 0; }
QToolButton#cardDelete { padding: 0 4px; color: %(faint)s; }
QToolButton#cardDelete:hover { color: %(danger)s; background: transparent; }
QToolButton#cardAction { padding: 0 4px; color: %(faint)s; }
QToolButton#cardAction:hover { color: %(accent)s; background: transparent; }
QLabel#locState { color: %(faint)s; font-size: 11px; }
QLabel#locState[state="ok"] { color: %(accent)s; }
QLabel#locState[state="missing"] { color: #F5A623; }
QComboBox { background: %(surface)s; border: 1px solid %(border)s; border-radius: 6px; padding: 3px 8px; }
QComboBox QAbstractItemView { background: %(bg_solid)s; border: 1px solid %(border)s; selection-background-color: %(surface_hover)s; }
QPlainTextEdit { background: %(surface)s; border: 1px solid %(border)s; border-radius: 6px; padding: 4px 6px;
                 selection-background-color: %(accent)s; }
QPlainTextEdit:focus { border-color: %(accent)s; }
QPlainTextEdit[invalid="true"] { border-color: %(danger)s; }
QCheckBox::indicator { width: 14px; height: 14px; }
QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }
QScrollBar:vertical { width: 8px; background: transparent; margin: 2px; }
QScrollBar::handle:vertical { background: %(border)s; border-radius: 3px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QMenu { background: %(bg_solid)s; border: 1px solid %(border)s; padding: 4px; }
QMenu::item { padding: 5px 18px; border-radius: 4px; }
QMenu::item:selected { background: %(surface_hover)s; }
QDialog { background: %(bg_solid)s; }
""" % C


def apply(app: QApplication) -> None:
    app.setStyle('Fusion')
    pal = QPalette()
    for role, color in ((QPalette.Window, C['bg_solid']), (QPalette.Base, C['surface']),
                        (QPalette.AlternateBase, C['surface_hover']), (QPalette.Button, C['surface']),
                        (QPalette.Text, C['text']), (QPalette.WindowText, C['text']),
                        (QPalette.ButtonText, C['text']), (QPalette.Highlight, C['accent']),
                        (QPalette.HighlightedText, '#FFFFFF'), (QPalette.ToolTipBase, C['bg_solid']),
                        (QPalette.ToolTipText, C['text']), (QPalette.PlaceholderText, C['faint'])):
        pal.setColor(role, QColor(color))
    app.setPalette(pal)
    app.setStyleSheet(STYLE)


def chip_style(color: str, selected: bool) -> str:
    c = QColor(color)
    bg = f'rgba({c.red()}, {c.green()}, {c.blue()}, {200 if selected else 28})'
    fg = '#FFFFFF' if selected else color
    return (f'QPushButton {{ background: {bg}; color: {fg}; border: 1px solid {color}; border-radius: 12px;'
            f' padding: 3px 10px; font-weight: {600 if selected else 400}; }}'
            f'QPushButton:hover {{ background: rgba({c.red()}, {c.green()}, {c.blue()}, {220 if selected else 60}); }}')
