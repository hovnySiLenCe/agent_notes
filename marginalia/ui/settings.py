"""Settings window: annotation types (name, color, hotkey, comment box, template), the prompt around them, and the
global hotkeys. Saving writes those sections of config.json (the rest of the file is kept) and reloads it."""
from __future__ import annotations

import copy
import html
import re
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox,
                               QTabWidget, QToolButton, QVBoxLayout, QWidget)

from .. import config as cfgmod
from ..core.composer import compose
from ..core.models import INPUT_NONE, INPUT_OPTIONAL, INPUT_REQUIRED, Annotation, AnnoType
from ..core.template import render
from .icons import icon
from .popup import Chip
from .theme import C, chip_style

INPUT_MODES = [(INPUT_NONE, '直接保存（不弹输入框）'), (INPUT_OPTIONAL, '可以写说明（可留空）'),
               (INPUT_REQUIRED, '必须写说明')]
GLOBAL_HOTKEYS = [('menu', '批注菜单', '选中文字后按下，弹出类型菜单'),
                  ('fill', '填入来源窗口', '把勾选的批注拼成提示语，填入批注来源窗口的输入框'),
                  ('fill_here', '在光标处填入', '同样的内容，输入在当前窗口的光标处'),
                  ('fill_plain', '仅填入引用', '只填入引用和说明，不带提示语和类型说明'),
                  ('toggle_panel', '显示 / 隐藏面板', '')]
SAMPLE_QUOTE = '这里是被选中的一段回复原文'
SAMPLE_COMMENT = '你写的说明'
NEW_COLORS = ['#4C8BF5', '#16A34A', '#F5A623', '#E5484D', '#8E4EC6', '#0EA5A4', '#C2185B', '#64748B']

# Qt key -> the key's name in a hotkey spec (X keysym names; letters and digits are themselves).
_NAMED = {Qt.Key_Return: 'Return', Qt.Key_Enter: 'Return', Qt.Key_Space: 'Space', Qt.Key_Tab: 'Tab',
          Qt.Key_Insert: 'Insert', Qt.Key_Delete: 'Delete', Qt.Key_Home: 'Home', Qt.Key_End: 'End',
          Qt.Key_PageUp: 'Prior', Qt.Key_PageDown: 'Next', Qt.Key_Up: 'Up', Qt.Key_Down: 'Down',
          Qt.Key_Left: 'Left', Qt.Key_Right: 'Right'}
# punctuation, including what Shift turns it into on a US layout (Shift+1 arrives as '!')
_PUNCT = {',': 'comma', '<': 'comma', '.': 'period', '>': 'period', '/': 'slash', '?': 'slash',
          ';': 'semicolon', ':': 'semicolon', "'": 'apostrophe', '"': 'apostrophe', '[': 'bracketleft',
          '{': 'bracketleft', ']': 'bracketright', '}': 'bracketright', '-': 'minus', '_': 'minus',
          '=': 'equal', '+': 'equal', '`': 'grave', '~': 'grave', '\\': 'backslash', '|': 'backslash',
          '!': '1', '@': '2', '#': '3', '$': '4', '%': '5', '^': '6', '&': '7', '*': '8', '(': '9', ')': '0'}
_MODS = ((Qt.ControlModifier, 'Ctrl'), (Qt.ShiftModifier, 'Shift'), (Qt.AltModifier, 'Alt'),
         (Qt.MetaModifier, 'Super'))


def key_name(key: int, text: str = '') -> str:
    """The spec name of a non-modifier key, or '' when it cannot be a hotkey."""
    if key in _NAMED:
        return _NAMED[key]
    if Qt.Key_F1 <= key <= Qt.Key_F24:
        return f'F{key - Qt.Key_F1 + 1}'
    if Qt.Key_A <= key <= Qt.Key_Z:
        return chr(key)
    if Qt.Key_0 <= key <= Qt.Key_9:
        return chr(key)
    ch = chr(key) if 32 < key < 127 else text
    return _PUNCT.get(ch, '')


def hotkey_spec(mods, key: int, text: str = '') -> str:
    """'Shift+Alt+Y' for a key press, or '' when it is not a usable global hotkey: a bare key (or Shift+key)
    would be taken away from every application, so Ctrl, Alt or Super is required (F-keys may stand alone)."""
    name = key_name(key, text)
    if not name:
        return ''
    held = [n for m, n in _MODS if mods & m]
    if not set(held) & {'Ctrl', 'Alt', 'Super'} and not re.fullmatch(r'F\d+', name):
        return ''
    return '+'.join(held + [name])


def _norm(spec: str) -> str:
    """Comparable form of a spec: 'alt+shift+y' == 'Shift+Alt+Y'."""
    parts = [p.strip().lower() for p in spec.split('+') if p.strip()]
    if not parts:
        return ''
    alias = {'control': 'ctrl', 'win': 'super', 'enter': 'return'}
    *mods, key = [alias.get(p, p) for p in parts]
    return '+'.join(sorted(mods) + [key])


class HotkeyEdit(QLineEdit):
    """Click, then press the combination. Backspace / Delete clears it, Esc keeps the old one.
    While recording, the app's own global hotkeys are released (else X would deliver the combo to them)."""
    changed = Signal(str)

    def __init__(self, suspend: Callable[[bool], None] | None = None):
        super().__init__()
        self.setReadOnly(True)
        self.setPlaceholderText('未设置')
        self.setFocusPolicy(Qt.ClickFocus)         # tabbing through must not start a recording
        self.setCursor(Qt.PointingHandCursor)
        self._spec = ''
        self._suspend = suspend
        self._recording = False

    def spec(self) -> str:
        return self._spec

    def set_spec(self, spec: str) -> None:
        self._spec = spec or ''
        self.setText(self._spec)

    def focusInEvent(self, e) -> None:
        super().focusInEvent(e)
        self._recording = True
        if self._suspend:
            self._suspend(True)
        self.setText('')
        self.setPlaceholderText('请按下组合键…（Backspace 清除，Esc 取消）')

    def focusOutEvent(self, e) -> None:
        super().focusOutEvent(e)
        self._stop()

    def _stop(self) -> None:
        if not self._recording:
            return
        self._recording = False
        if self._suspend:
            self._suspend(False)
        self.setPlaceholderText('未设置')
        self.setText(self._spec)

    def keyPressEvent(self, e: QKeyEvent) -> None:
        key = e.key()
        if key in (Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_Super_L, Qt.Key_Super_R,
                   Qt.Key_AltGr):
            held = [n for m, n in _MODS if e.modifiers() & m]
            self.setText('+'.join(held) + '+…')
            return
        mods = e.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier | Qt.AltModifier | Qt.MetaModifier)
        if not mods and key == Qt.Key_Escape:
            self.clearFocus()
            return
        if not mods and key in (Qt.Key_Backspace, Qt.Key_Delete):
            self._spec = ''
            self.changed.emit('')
            self.clearFocus()
            return
        spec = hotkey_spec(mods, key, e.text())
        if not spec:
            self.setText('')
            self.setPlaceholderText('需要包含 Ctrl、Alt 或 Super，例如 Shift+Alt+Y')
            return
        self._spec = spec
        self.changed.emit(spec)
        self.clearFocus()

    def keyReleaseEvent(self, e: QKeyEvent) -> None:
        if self._recording and not self._spec and not (e.modifiers() & ~Qt.KeypadModifier):
            self.setText('')

    def clearFocus(self) -> None:
        super().clearFocus()
        self._stop()


class ColorButton(QPushButton):
    changed = Signal(str)

    def __init__(self):
        super().__init__()
        self._color = '#7C8594'
        self.setCursor(Qt.PointingHandCursor)
        self.clicked.connect(self._pick)

    def color(self) -> str:
        return self._color

    def set_color(self, color: str) -> None:
        self._color = QColor(color).name().upper() if QColor(color).isValid() else '#7C8594'
        self.setText(self._color)
        self.setStyleSheet('QPushButton { text-align: left; }')
        self.setIcon(self._swatch())

    def _swatch(self):
        from PySide6.QtGui import QIcon, QPainter, QPixmap
        pm = QPixmap(14, 14)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(self._color))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(0, 0, 14, 14, 4, 4)
        p.end()
        return QIcon(pm)

    def _pick(self) -> None:
        c = QColorDialog.getColor(QColor(self._color), self.window(), '批注类型颜色')
        if c.isValid():
            self.set_color(c.name())
            self.changed.emit(self._color)


class TypesPage(QWidget):
    changed = Signal()

    def __init__(self, types: list[dict], suspend, usage: Callable[[str], int]):
        super().__init__()
        self.types = copy.deepcopy(types)
        self._usage = usage
        self._loading = False
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 12, 0, 0)
        root.setSpacing(16)

        left = QVBoxLayout()
        left.setSpacing(8)
        self.list = QListWidget(objectName='typeList')
        self.list.setFixedWidth(220)
        self.list.currentRowChanged.connect(self._show)
        left.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.setSpacing(4)
        self.add_btn = self._tool('新增类型', '＋')
        self.del_btn = self._tool('删除类型', '', 'trash')
        self.up_btn = self._tool('上移（菜单和划词按钮里的顺序）', '↑')
        self.down_btn = self._tool('下移', '↓')
        self.add_btn.clicked.connect(self.add_type)
        self.del_btn.clicked.connect(self.delete_type)
        self.up_btn.clicked.connect(lambda: self.move(-1))
        self.down_btn.clicked.connect(lambda: self.move(1))
        for b in (self.add_btn, self.up_btn, self.down_btn):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(self.del_btn)
        left.addLayout(row)
        order = QLabel('前 4 个显示在划词按钮上；菜单里按 1-9、0 选前 10 个', objectName='faint')
        order.setWordWrap(True)
        order.setFixedWidth(220)
        left.addWidget(order)
        root.addLayout(left)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        self.name = QLineEdit()
        self.name.setMaxLength(12)
        self.name.textEdited.connect(lambda v: self._set('name', v.strip()))
        self.color = ColorButton()
        self.color.changed.connect(lambda v: self._set('color', v))
        self.hotkey = HotkeyEdit(suspend)
        self.hotkey.changed.connect(lambda v: self._set('hotkey', v))
        self.input = QComboBox()
        for _value, label in INPUT_MODES:
            self.input.addItem(label)
        self.input.currentIndexChanged.connect(lambda i: self._set('input', INPUT_MODES[i][0]))
        self.template = QPlainTextEdit()
        self.template.setFixedHeight(84)
        self.template.textChanged.connect(lambda: self._set('template', self.template.toPlainText()))
        inserts = QHBoxLayout()
        inserts.setSpacing(6)
        for label, text in (('引用', '{{quote}}'), ('说明', '{{comment}}'), ('名称', '{{name}}'),
                            ('有说明时才输出…', '{{#comment}}{{comment}}{{/comment}}')):
            b = QPushButton(label, objectName='small')
            b.setToolTip(f'插入 {text}')
            b.clicked.connect(lambda _=False, t=text: self._insert(t))
            inserts.addWidget(b)
        inserts.addStretch(1)
        self.chip_box = QHBoxLayout()
        self.chip_box.setContentsMargins(0, 0, 0, 0)
        chip_row = QWidget()
        chip_row.setLayout(self.chip_box)
        self.id_label = QLabel(objectName='faint')
        self.chip_box.addStretch(1)
        self.chip_box.addWidget(self.id_label)
        self.preview = QLabel(objectName='preview')
        self.preview.setWordWrap(True)
        self.preview.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.preview.setTextFormat(Qt.RichText)
        self.preview.setTextInteractionFlags(Qt.TextSelectableByMouse)

        form.addRow('外观', chip_row)
        form.addRow('名称', self.name)
        form.addRow('颜色', self.color)
        form.addRow('快捷键', self.hotkey)
        form.addRow('说明输入', self.input)
        form.addRow('模板', self.template)
        form.addRow('', self._wrap(inserts))
        form.addRow('预览', self.preview)
        self.form_box = QWidget()
        self.form_box.setLayout(form)
        root.addWidget(self.form_box, 1)
        self._chip: Chip | None = None
        self._reload_list()
        self.list.setCurrentRow(0)

    @staticmethod
    def _wrap(layout) -> QWidget:
        w = QWidget()
        layout.setContentsMargins(0, 0, 0, 0)
        w.setLayout(layout)
        return w

    def _tool(self, tip: str, text: str = '', icon_name: str = '') -> QToolButton:
        b = QToolButton()
        b.setToolTip(tip)
        b.setFixedSize(30, 28)
        if icon_name:
            b.setIcon(icon(icon_name, C['muted'], C['text']))
        else:
            b.setText(text)
        return b

    # ---- list -----------------------------------------------------------------------------------------------
    def _reload_list(self) -> None:
        cur = self.list.currentRow()
        self.list.blockSignals(True)
        self.list.clear()
        for i, t in enumerate(self.types):
            self.list.addItem(self._item(i, t))
        self.list.blockSignals(False)
        if self.types:
            self.list.setCurrentRow(max(0, min(cur, len(self.types) - 1)))
        self._sync_buttons()

    def _item(self, i: int, t: dict) -> QListWidgetItem:
        key = '1234567890'[i] if i < 10 else ' '
        hk = f'   {t["hotkey"]}' if t.get('hotkey') else ''
        it = QListWidgetItem(f'{key}  {t.get("name") or "（未命名）"}{hk}')
        it.setIcon(self._dot(t.get('color', '#7C8594')))
        return it

    @staticmethod
    def _dot(color: str):
        from PySide6.QtGui import QIcon, QPainter, QPixmap
        pm = QPixmap(12, 12)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(color) if QColor(color).isValid() else QColor('#7C8594'))
        p.setPen(Qt.NoPen)
        p.drawEllipse(1, 1, 10, 10)
        p.end()
        return QIcon(pm)

    def _sync_buttons(self) -> None:
        i = self.list.currentRow()
        self.del_btn.setEnabled(len(self.types) > 1 and i >= 0)
        self.up_btn.setEnabled(i > 0)
        self.down_btn.setEnabled(0 <= i < len(self.types) - 1)
        self.form_box.setEnabled(i >= 0)

    def current(self) -> dict | None:
        i = self.list.currentRow()
        return self.types[i] if 0 <= i < len(self.types) else None

    def _show(self, _row: int) -> None:
        self._sync_buttons()
        t = self.current()
        if t is None:
            return
        self._loading = True
        self.name.setText(t.get('name', ''))
        self.color.set_color(t.get('color', '#7C8594'))
        self.hotkey.set_spec(t.get('hotkey', ''))
        modes = [m for m, _ in INPUT_MODES]
        self.input.setCurrentIndex(modes.index(t.get('input', INPUT_OPTIONAL)) if t.get('input') in modes else 1)
        self.template.setPlainText(t.get('template', ''))
        self._loading = False
        self._refresh_current()

    def _set(self, key: str, value) -> None:
        t = self.current()
        if self._loading or t is None or t.get(key) == value:
            return
        t[key] = value
        self._refresh_current()
        self.changed.emit()

    def _insert(self, text: str) -> None:
        self.template.insertPlainText(text)
        self.template.setFocus()

    def _refresh_current(self) -> None:
        i = self.list.currentRow()
        t = self.current()
        if t is None:
            return
        self.list.item(i).setText(self._item(i, t).text())
        self.list.item(i).setIcon(self._dot(t.get('color', '#7C8594')))
        if self._chip is not None:
            self.chip_box.removeWidget(self._chip)
            self._chip.setParent(None)
            self._chip.deleteLater()
        self._chip = Chip('1234567890'[i] if i < 10 else '', t.get('name') or '（未命名）')
        self._chip.setStyleSheet(chip_style(t.get('color', '#7C8594'), False))
        self._chip.setFixedWidth(120)
        self._chip.setFocusPolicy(Qt.NoFocus)
        self.chip_box.insertWidget(0, self._chip)
        self.id_label.setText(f'id：{t["id"]}')
        self.preview.setText(self._preview(t))

    @staticmethod
    def _preview(t: dict) -> str:
        at = AnnoType.from_dict({**t, 'name': t.get('name') or t['id']})
        cases = []
        if at.input != INPUT_REQUIRED:
            cases.append(('不写说明', ''))
        if at.input != INPUT_NONE:
            cases.append(('写了说明', SAMPLE_COMMENT))
        rows = []
        for label, comment in cases:
            ann = Annotation(at.id, SAMPLE_QUOTE, comment=comment)
            text = compose([ann], {at.id: at}, {'header': '', 'footer': ''})[3:]   # drop the '1. '
            rows.append(f'<span style="color:{C["faint"]}">{label}：</span>{html.escape(text)}')
        return '<br>'.join(rows)

    # ---- edits ----------------------------------------------------------------------------------------------
    def add_type(self) -> None:
        ids = {t['id'] for t in self.types}
        n = 1
        while f'custom{n}' in ids:
            n += 1
        color = NEW_COLORS[len(self.types) % len(NEW_COLORS)]
        self.types.append({'id': f'custom{n}', 'name': f'类型{n}', 'color': color, 'hotkey': '',
                           'input': INPUT_OPTIONAL,
                           'template': f'【类型{n}】{{{{#quote}}}}「{{{{quote}}}}」{{{{/quote}}}}→ {{{{comment}}}}'})
        self._reload_list()
        self.list.setCurrentRow(len(self.types) - 1)
        self.name.setFocus()
        self.name.selectAll()
        self.changed.emit()

    def delete_type(self, confirm: bool = True) -> None:
        t = self.current()
        if t is None or len(self.types) <= 1:
            return
        used = self._usage(t['id'])
        if confirm:
            msg = f'删除批注类型「{t.get("name")}」？'
            if used:
                msg += f'\n\n已有 {used} 条批注属于这个类型：它们会保留，但会显示为 “{t["id"]}”，填入时使用默认格式。'
            if QMessageBox.question(self.window(), '删除类型', msg) != QMessageBox.Yes:
                return
        i = self.list.currentRow()
        del self.types[i]
        self._reload_list()
        self.list.setCurrentRow(min(i, len(self.types) - 1))
        self.changed.emit()

    def move(self, step: int) -> None:
        i = self.list.currentRow()
        j = i + step
        if not (0 <= i < len(self.types) and 0 <= j < len(self.types)):
            return
        self.types[i], self.types[j] = self.types[j], self.types[i]
        self._reload_list()
        self.list.setCurrentRow(j)
        self.changed.emit()

    def set_types(self, types: list[dict]) -> None:
        self.types = copy.deepcopy(types)
        self._reload_list()
        self.list.setCurrentRow(0)
        self._show(0)
        self.changed.emit()


class PromptPage(QWidget):
    changed = Signal()

    def __init__(self, prompt: dict, types_page: TypesPage):
        super().__init__()
        self._types = types_page
        lay = QFormLayout(self)
        lay.setContentsMargins(0, 12, 0, 0)
        lay.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.setHorizontalSpacing(12)
        lay.setVerticalSpacing(10)
        self.header = QPlainTextEdit()
        self.header.setFixedHeight(56)
        self.footer = QPlainTextEdit()
        self.footer.setFixedHeight(56)
        self.footer.setPlaceholderText('（可留空）')
        self.quote_max = QSpinBox()
        self.quote_max.setRange(0, 5000)
        self.quote_max.setSpecialValueText('不限制')
        self.quote_max.setSuffix(' 字')
        self.quote_max.setFixedWidth(120)
        self.newline = QCheckBox(' 填入后多加一个换行（终端里不加，以免直接执行）')
        self.plain = QLineEdit()
        self.preview = QLabel(objectName='preview')
        self.preview.setWordWrap(True)
        self.preview.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.preview.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addRow('开头', self.header)
        lay.addRow('结尾', self.footer)
        lay.addRow('引用最长', self.quote_max)
        lay.addRow('', self.newline)
        lay.addRow('仅引用格式', self.plain)
        lay.addRow('预览', self.preview)
        self.set_prompt(prompt)
        for w in (self.header, self.footer):
            w.textChanged.connect(self._edited)
        self.quote_max.valueChanged.connect(self._edited)
        self.newline.toggled.connect(self._edited)
        self.plain.textEdited.connect(self._edited)
        types_page.changed.connect(self.update_preview)

    def set_prompt(self, prompt: dict) -> None:
        self._prompt = copy.deepcopy(prompt)
        for w in (self.header, self.footer, self.quote_max, self.newline, self.plain):
            w.blockSignals(True)
        self.header.setPlainText(prompt.get('header', ''))
        self.footer.setPlainText(prompt.get('footer', ''))
        self.quote_max.setValue(int(prompt.get('quote_max_chars', 0) or 0))
        self.newline.setChecked(bool(prompt.get('trailing_newline')))
        self.plain.setText(prompt.get('plain_template', ''))
        for w in (self.header, self.footer, self.quote_max, self.newline, self.plain):
            w.blockSignals(False)
        self.update_preview()

    def prompt(self) -> dict:
        return dict(self._prompt, header=self.header.toPlainText(), footer=self.footer.toPlainText(),
                    quote_max_chars=self.quote_max.value(), trailing_newline=self.newline.isChecked(),
                    plain_template=self.plain.text())

    def _edited(self, *_a) -> None:
        self.update_preview()
        self.changed.emit()

    def update_preview(self) -> None:
        types = []
        for t in self._types.types:
            try:
                types.append(AnnoType.from_dict({**t, 'name': t.get('name') or t['id']}))
            except (ValueError, TypeError):
                pass
        sample = []
        for t in types[:3]:
            comment = '' if t.input == INPUT_NONE else SAMPLE_COMMENT
            sample.append(Annotation(t.id, SAMPLE_QUOTE, comment=comment))
        text = compose(sample, {t.id: t for t in types}, self.prompt())
        body = html.escape(text).replace('\n', '<br>')
        if self.newline.isChecked():
            body += f'<br><span style="color:{C["faint"]}">↵（光标停在这里）</span>'
        self.preview.setText(body)


class HotkeysPage(QWidget):
    changed = Signal()

    def __init__(self, hotkeys: dict, suspend):
        super().__init__()
        self._hotkeys = copy.deepcopy(hotkeys)
        lay = QFormLayout(self)
        lay.setContentsMargins(0, 12, 0, 0)
        lay.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.setHorizontalSpacing(12)
        lay.setVerticalSpacing(12)
        self.edits: dict[str, HotkeyEdit] = {}
        for action, label, tip in GLOBAL_HOTKEYS:
            e = HotkeyEdit(suspend)
            e.setFixedWidth(220)
            e.setToolTip(tip)
            e.changed.connect(lambda *_: self.changed.emit())
            self.edits[action] = e
            row = QHBoxLayout()
            row.setSpacing(10)
            row.addWidget(e)
            note = QLabel(tip, objectName='faint')
            row.addWidget(note, 1)
            lay.addRow(label, TypesPage._wrap(row))
        hint = QLabel('点击输入框后按下组合键；Backspace 清除（不绑定），Esc 取消。'
                      '每个批注类型自己的快捷键在“批注类型”里设置。', objectName='faint')
        hint.setWordWrap(True)
        lay.addRow('', hint)
        self.set_hotkeys(hotkeys)

    def set_hotkeys(self, hotkeys: dict) -> None:
        self._hotkeys = copy.deepcopy(hotkeys)
        for action, e in self.edits.items():
            e.set_spec(hotkeys.get(action, ''))

    def hotkeys(self) -> dict:
        return dict(self._hotkeys, **{a: e.spec() for a, e in self.edits.items()})


class SettingsWindow(QWidget):
    """ctl: needs cfg, store, reload_config(); suspend_hotkeys(bool) is used when present."""

    def __init__(self, ctl):
        super().__init__(None, Qt.Window)
        self.ctl = ctl
        self.setObjectName('settings')
        self.setWindowTitle('Marginalia 设置')
        self.setWindowIcon(icon('note', C['accent']))
        self.resize(860, 620)
        suspend = getattr(ctl, 'suspend_hotkeys', None)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(10)
        self.tabs = QTabWidget()
        self.types_page = TypesPage(ctl.cfg.data['types'], suspend, self._usage)
        self.prompt_page = PromptPage(ctl.cfg.data['prompt'], self.types_page)
        self.hotkeys_page = HotkeysPage(ctl.cfg.data['hotkeys'], suspend)
        self.tabs.addTab(self.types_page, '批注类型')
        self.tabs.addTab(self.prompt_page, '提示语')
        self.tabs.addTab(self.hotkeys_page, '全局快捷键')
        lay.addWidget(self.tabs, 1)
        self.error = QLabel(objectName='error')
        self.error.setWordWrap(True)
        self.error.hide()
        lay.addWidget(self.error)
        self.status = QLabel(objectName='saved')
        self.status.setStyleSheet(f'color: {C["ok"]}; font-size: 12px;')
        self.status.hide()
        lay.addWidget(self.status)
        bar = QHBoxLayout()
        self.reset_btn = QPushButton('恢复本页默认值')
        self.reset_btn.clicked.connect(self.reset_page)
        self.file_btn = QPushButton('打开配置文件')
        self.file_btn.setToolTip('其余设置（面板、高亮、划词按钮、填入方式）在配置文件里修改')
        self.file_btn.clicked.connect(lambda: getattr(ctl, 'open_config', lambda: None)())
        self.cancel_btn = QPushButton('关闭')
        self.cancel_btn.clicked.connect(self.close)
        self.save_btn = QPushButton('保存', objectName='primary')
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self.save)
        bar.addWidget(self.reset_btn)
        bar.addWidget(self.file_btn)
        bar.addStretch(1)
        bar.addWidget(self.cancel_btn)
        bar.addWidget(self.save_btn)
        lay.addLayout(bar)
        self._dirty = False
        for page in (self.types_page, self.prompt_page, self.hotkeys_page):
            page.changed.connect(self._edited)
        self._sync_save()

    def _usage(self, type_id: str) -> int:
        try:
            return sum(1 for a in self.ctl.store.all() if a.type_id == type_id)
        except Exception:   # noqa: BLE001 - only used for a warning
            return 0

    def load(self) -> None:
        """Discard edits and show what the current config says."""
        data = self.ctl.cfg.data
        self.types_page.set_types(data['types'])
        self.prompt_page.set_prompt(data['prompt'])
        self.hotkeys_page.set_hotkeys(data['hotkeys'])
        self._dirty = False
        self._sync_save()

    def _edited(self) -> None:
        self._dirty = True
        self.status.hide()
        self._sync_save()

    def problems(self) -> list[str]:
        out = []
        names = [t.get('name', '').strip() for t in self.types_page.types]
        if any(not n for n in names):
            out.append('有批注类型没有名称')
        dup = sorted({n for n in names if n and names.count(n) > 1})
        if dup:
            out.append(f'批注类型重名：{"、".join(dup)}')
        owners: dict[str, list[str]] = {}
        shown: dict[str, str] = {}
        labels = {a: label for a, label, _ in GLOBAL_HOTKEYS}
        pairs = [(spec, labels.get(a, a)) for a, spec in self.hotkeys_page.hotkeys().items()]
        pairs += [(t.get('hotkey', ''), f'「{t.get("name") or t["id"]}」') for t in self.types_page.types]
        for spec, who in pairs:
            if spec:
                owners.setdefault(_norm(spec), []).append(who)
                shown.setdefault(_norm(spec), spec)
        for key, who in owners.items():
            if len(who) > 1:
                out.append(f'快捷键 {shown[key]} 同时分配给了 {"、".join(who)}')
        return out

    def _sync_save(self) -> None:
        problems = self.problems()
        self.error.setText('；'.join(problems))
        self.error.setVisible(bool(problems))
        self.save_btn.setEnabled(self._dirty and not problems)
        self.setWindowTitle('Marginalia 设置' + (' •' if self._dirty else ''))

    def save(self) -> bool:
        if self.problems():
            self._sync_save()
            return False
        types = [{k: v for k, v in t.items()} for t in self.types_page.types]
        for t in types:
            t['name'] = t['name'].strip()
        try:
            backup = cfgmod.save_sections({'types': types, 'prompt': self.prompt_page.prompt(),
                                           'hotkeys': self.hotkeys_page.hotkeys()})
        except (OSError, ValueError) as e:
            self.error.setText(f'保存失败：{e}')
            self.error.show()
            return False
        self._dirty = False
        self._sync_save()
        getattr(self.ctl, 'reload_config', lambda: None)()
        self.status.setText(f'已保存并生效（原文件备份为 {backup.name}）' if backup else '已保存并生效')
        self.status.show()
        return True

    def reset_page(self) -> None:
        page = self.tabs.currentWidget()
        name = self.tabs.tabText(self.tabs.currentIndex())
        if QMessageBox.question(self, '恢复默认值', f'把“{name}”恢复成默认设置？（点保存后才会生效）') != QMessageBox.Yes:
            return
        self.reset(page)

    def reset(self, page: QWidget) -> None:
        d = cfgmod.DEFAULTS
        if page is self.types_page:
            self.types_page.set_types(d['types'])
        elif page is self.prompt_page:
            self.prompt_page.set_prompt(d['prompt'])
        else:
            self.hotkeys_page.set_hotkeys(d['hotkeys'])
        self._edited()

    def closeEvent(self, e) -> None:
        if self._dirty:
            box = QMessageBox(QMessageBox.Question, '未保存', '设置有修改还没保存。', parent=self)
            save = box.addButton('保存', QMessageBox.AcceptRole)
            drop = box.addButton('放弃修改', QMessageBox.DestructiveRole)
            box.addButton('取消', QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is save:
                if not self.save():
                    e.ignore()
                    return
            elif box.clickedButton() is drop:
                self.load()
            else:
                e.ignore()
                return
        super().closeEvent(e)

    def showEvent(self, e) -> None:
        if not self._dirty:
            self.load()        # pick up edits made in the file since last time
        super().showEvent(e)
