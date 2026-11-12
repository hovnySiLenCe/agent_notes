"""The always-on-top floating panel that holds pending annotations."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QMimeData, QPoint, QPropertyAnimation, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QDrag, QGuiApplication, QIcon, QPainter
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFrame,
                               QHBoxLayout, QLabel, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
                               QSizeGrip, QToolButton, QVBoxLayout, QWidget)

from ..core.models import PENDING, RESOLVED, SENT, Annotation, AnnoType
from .icons import icon, pixmap
from .theme import C, add_shadow, margin, quote_block, rgba, type_tag_style

if TYPE_CHECKING:
    from ..app import Controller

MIME = 'application/x-marginalia-id'
MIN_SIZE = (300, 160)          # expanded panel's frame: room for the header and at least one card


def min_size() -> tuple[int, int]:
    return MIN_SIZE[0] + 2 * margin(), MIN_SIZE[1] + 2 * margin()
APP_NAMES = {'firefox': 'Firefox', 'firefox_firefox': 'Firefox', 'code': 'VS Code', 'google-chrome': 'Chrome', 'chromium': 'Chromium',
             'chromium-browser': 'Chromium', 'gnome-terminal-server': '终端', 'cursor': 'Cursor'}


def app_label(source: dict) -> str:
    cls = (source.get('wm_class') or '').lower()
    return APP_NAMES.get(cls) or source.get('app') or source.get('wm_class') or '未知来源'


def source_label(source: dict, n: int = 40) -> str:
    title = source.get('title') or ''
    title = title if len(title) <= n else title[:n - 1] + '…'
    return f'{app_label(source)} · {title}' if title else app_label(source)


def short_hotkey(spec: str) -> str:
    """'Shift+Alt+Return' -> '⇧⌥↵' for button labels."""
    sym = {'shift': '⇧', 'alt': '⌥', 'ctrl': '⌃', 'control': '⌃', 'super': '❖', 'return': '↵', 'enter': '↵',
           'space': '␣'}
    return ''.join(sym.get(p.strip().lower(), p.strip().upper()) for p in spec.split('+') if p.strip())


def _elide(text: str, n: int) -> str:
    t = ' '.join(text.split())
    return t if len(t) <= n else t[:n - 1] + '…'


class Card(QFrame):
    def __init__(self, ann: Annotation, atype: AnnoType, panel: 'FloatingPanel'):
        super().__init__(objectName='card')
        self.ann, self.panel = ann, panel
        self._press: QPoint | None = None
        self.setProperty('sent', ann.status != PENDING)        # dimmed: already sent or resolved
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 8, 10)
        lay.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(7)
        self.check = QCheckBox()
        self.check.setChecked(ann.checked)
        self.check.setToolTip('勾选后会再次填入' if ann.status == SENT else '勾选的批注会被填入')
        self.check.toggled.connect(lambda on: panel.ctl.store.update(ann.id, checked=on))
        name = QLabel(atype.name)
        name.setStyleSheet(type_tag_style(atype.color))
        src = QLabel(_elide(app_label(ann.source), 18), objectName='faint')
        src.setToolTip(source_label(ann.source, 200))
        top.addWidget(self.check)
        top.addWidget(name)
        top.addWidget(src)
        top.addStretch(1)
        if ann.status == SENT:
            top.addWidget(QLabel('已发送', objectName='badge'))
        elif ann.status == RESOLVED:
            top.addWidget(QLabel('✓ 已解决', objectName='badgeDone'))
        top.addWidget(QLabel(time.strftime('%H:%M', time.localtime(ann.created_at)), objectName='faint'))
        self.loc = QLabel('', objectName='locState')      # where the quote is in its window right now
        self.loc.hide()
        top.addWidget(self.loc)
        self.jump_btn = self._hover_button('target', '跳到原文（双击卡片也可以）', lambda: panel.jump(ann))
        if ann.status == RESOLVED:
            self.done_btn = self._hover_button('undo', '重新打开（改回待发送）', lambda: panel.set_status(ann, PENDING))
        else:
            self.done_btn = self._hover_button('check', '标记为已解决（不再填入，原文不再高亮）',
                                               lambda: panel.set_status(ann, RESOLVED))
        self.del_btn = self._hover_button('close', '删除这条批注', lambda: panel.ctl.store.delete([ann.id]))
        top.addWidget(self.jump_btn)
        top.addWidget(self.done_btn)
        top.addWidget(self.del_btn)
        lay.addLayout(top)
        if ann.quote.strip():
            q = QLabel(_elide(ann.quote, 150), objectName='quote')
            q.setWordWrap(True)
            q.setToolTip(ann.quote[:2000])
            lay.addWidget(quote_block(q, rgba(atype.color, 150) if ann.status == PENDING else C['border_strong']))
        if ann.comment.strip():
            c = QLabel(ann.comment.strip(), objectName='comment')
            c.setWordWrap(True)
            lay.addWidget(c)

    def _hover_button(self, name: str, tip: str, slot) -> QToolButton:
        b = QToolButton(objectName='cardDelete' if name == 'close' else 'cardAction')
        hover = C['danger'] if name == 'close' else C['text']
        b.setIcon(icon(name, C['faint'], hover, 14))
        b.setToolTip(tip)
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(slot)
        sp = b.sizePolicy()
        sp.setRetainSizeWhenHidden(True)      # no layout jump when it appears on hover
        b.setSizePolicy(sp)
        b.hide()
        return b

    LOC_TEXT = {'ok': ('◉', '原文在窗口中可见，已高亮'), 'offscreen': ('○', '原文已滚出视野：点 ⌖ 跳过去'),
                'missing': ('⚠', '在来源窗口中没找到这段原文（页面已关闭或内容已变）')}

    def set_locate_state(self, state: str | None) -> None:
        text, tip = self.LOC_TEXT.get(state or '', ('', ''))
        self.loc.setText(text)
        self.loc.setToolTip(tip)
        self.loc.setProperty('state', state or '')
        self.loc.style().unpolish(self.loc)
        self.loc.style().polish(self.loc)
        self.loc.setVisible(bool(text))

    def enterEvent(self, e) -> None:
        for b in (self.jump_btn, self.done_btn, self.del_btn):
            b.show()
        self.panel.hover(self.ann.id)
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        for b in (self.jump_btn, self.done_btn, self.del_btn):
            b.hide()
        self.panel.hover(None)
        super().leaveEvent(e)

    def mouseDoubleClickEvent(self, e) -> None:
        self.panel.jump(self.ann)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            self._press = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e) -> None:
        if self._press is None or (e.position().toPoint() - self._press).manhattanLength() \
                < QApplication.startDragDistance():
            return
        self._press = None
        mime = QMimeData()
        mime.setData(MIME, self.ann.id.encode())
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(self.grab())
        drag.setHotSpot(e.position().toPoint())
        drag.exec(Qt.MoveAction)

    def mouseReleaseEvent(self, e) -> None:
        self._press = None
        super().mouseReleaseEvent(e)

    def contextMenuEvent(self, e) -> None:
        a, ctl = self.ann, self.panel.ctl
        m = QMenu(self)
        m.addAction('跳到原文', lambda: self.panel.jump(a))
        m.addAction('编辑', lambda: self.panel.edit(a.id))
        m.addAction('复制引用原文', lambda: QGuiApplication.clipboard().setText(a.quote))
        if a.status != PENDING:
            m.addAction('标记为待发送', lambda: self.panel.set_status(a, PENDING))
        if a.status == PENDING:
            m.addAction('标记为已发送', lambda: self.panel.set_status(a, SENT))
        if a.status != RESOLVED:
            m.addAction('标记为已解决', lambda: self.panel.set_status(a, RESOLVED))
        m.addSeparator()
        m.addAction('删除', lambda: ctl.store.delete([a.id]))
        m.exec(e.globalPos())


class CardList(QWidget):
    """Vertical list of cards that supports drag-to-reorder."""
    reordered = Signal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(8, 4, 8, 4)
        self._lay.setSpacing(6)
        self._lay.addStretch(1)
        self._cards: list[Card] = []
        self._drop_y: int | None = None

    def set_widgets(self, cards: list[Card], empty: QWidget | None) -> None:
        while self._lay.count() > 1:
            w = self._lay.takeAt(0).widget()
            if w is not None:
                w.hide()            # deleteLater() alone leaves the old card painted until the loop runs
                w.deleteLater()
        self._cards = cards
        for i, c in enumerate(cards):
            self._lay.insertWidget(i, c)
        if empty is not None:
            self._lay.insertWidget(0, empty)

    def _index_at(self, y: int) -> int:
        for i, c in enumerate(self._cards):
            if y < c.geometry().center().y():
                return i
        return len(self._cards)

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasFormat(MIME):
            e.acceptProposedAction()

    def dragMoveEvent(self, e) -> None:
        i = self._index_at(e.position().toPoint().y())
        if self._cards:
            self._drop_y = (self._cards[i].geometry().top() - 3 if i < len(self._cards)
                            else self._cards[-1].geometry().bottom() + 3)
        self.update()
        e.acceptProposedAction()

    def dragLeaveEvent(self, e) -> None:
        self._drop_y = None
        self.update()

    def dropEvent(self, e) -> None:
        moved = bytes(e.mimeData().data(MIME)).decode()
        i = self._index_at(e.position().toPoint().y())
        ids = [c.ann.id for c in self._cards]
        if moved in ids:
            before = ids[i] if i < len(ids) else None
            ids.remove(moved)
            ids.insert(ids.index(before) if before in ids else len(ids), moved)
            self.reordered.emit(ids)
        self._drop_y = None
        e.acceptProposedAction()

    def paintEvent(self, e) -> None:
        super().paintEvent(e)
        if self._drop_y is not None:
            p = QPainter(self)
            p.fillRect(QRect(10, self._drop_y - 1, self.width() - 20, 2), QColor(C['accent']))


class EditDialog(QDialog):
    def __init__(self, ann: Annotation, types: list[AnnoType], parent: QWidget):
        super().__init__(parent)
        self.setWindowTitle('编辑批注')
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        if ann.quote.strip():
            q = QLabel(f'「{_elide(ann.quote, 300)}」', objectName='quote')
            q.setWordWrap(True)
            lay.addWidget(q)
        self.type = QComboBox()
        for t in types:
            self.type.addItem(t.name, t.id)
        idx = self.type.findData(ann.type_id)
        self.type.setCurrentIndex(max(idx, 0))
        self.comment = QPlainTextEdit(ann.comment)
        self.comment.setPlaceholderText('补充说明 / 追问内容')
        self.comment.setFixedHeight(96)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText('保存')
        buttons.button(QDialogButtonBox.Cancel).setText('取消')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        for w in (self.type, self.comment, buttons):
            lay.addWidget(w)


class FloatingPanel(QWidget):
    _settle_until = 0.0         # until then, sizes reported by the window manager are not saved

    def __init__(self, ctl: 'Controller'):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.ctl = ctl
        self.setWindowTitle('Marginalia')
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMinimumSize(*min_size())
        self._collapsed = False
        self._pinned = bool(ctl.state.get('panel', {}).get('pinned', False))
        self._expanded_geo = QRect()
        self._poller = QTimer(self, interval=self.POLL_MS, timeout=self._track_pointer)
        self._grace_until = 0.0
        self._filter = ''          # '' = all sources
        self._save_timer = QTimer(self, singleShot=True, interval=600, timeout=self._save_geometry)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(margin(), margin(), margin(), margin())
        frame = QFrame(objectName='panel')
        add_shadow(frame)
        outer.addWidget(frame)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # header (drag handle)
        self._header = QWidget()
        self._header.setCursor(Qt.SizeAllCursor)
        hl = QHBoxLayout(self._header)
        hl.setContentsMargins(12, 8, 6, 8)
        hl.setSpacing(4)
        logo = QLabel()
        logo.setPixmap(pixmap('note', C['accent'], 16))
        self._title = QLabel('批注', objectName='title')
        self._count = QLabel('', objectName='countPill')
        self._count.hide()
        hl.addWidget(logo)
        hl.addSpacing(2)
        hl.addWidget(self._title)
        hl.addSpacing(4)
        hl.addWidget(self._count)
        hl.addStretch(1)
        self._menu_btn = self._tool('more', '菜单')
        self._menu_btn.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self)
        self._hl_action = menu.addAction('在原文上显示高亮')
        self._hl_action.setCheckable(True)
        self._hl_action.toggled.connect(self._toggle_highlight)
        self._bubble_action = menu.addAction('选中文字后显示批注按钮')
        self._bubble_action.setCheckable(True)
        self._bubble_action.toggled.connect(lambda on: ctl.set_bubble_enabled(on))
        menu.aboutToShow.connect(self._sync_menu)
        menu.addSeparator()
        menu.addAction('打开配置文件', ctl.open_config)
        menu.addAction('重新加载配置', ctl.reload_config)
        menu.addSeparator()
        menu.addAction('退出', ctl.quit)
        self._menu_btn.setMenu(menu)
        self._trash_btn = self._tool('trash', '删除 / 清空')
        self._trash_btn.setPopupMode(QToolButton.InstantPopup)
        self._trash_menu = QMenu(self)
        self._trash_menu.aboutToShow.connect(self._fill_trash_menu)
        self._trash_btn.setMenu(self._trash_menu)
        self._pin_btn = self._tool('pin', '固定展开：鼠标离开后不自动收起')
        self._pin_btn.setCheckable(True)
        self._pin_btn.setChecked(self._pinned)
        self._pin_btn.toggled.connect(self.set_pinned)
        self._close_btn = self._tool('close', '隐藏')
        self._close_btn.clicked.connect(self.hide)
        for b in (self._trash_btn, self._menu_btn, self._pin_btn, self._close_btn):
            hl.addWidget(b)
        lay.addWidget(self._header)

        # body
        self._body = QWidget()
        bl = QVBoxLayout(self._body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(6)
        fl = QHBoxLayout()
        fl.setContentsMargins(10, 0, 10, 2)
        self._filter_box = QComboBox()
        self._filter_box.currentIndexChanged.connect(self._on_filter)
        fl.addWidget(self._filter_box, 1)
        bl.addLayout(fl)
        self._list = CardList()
        self._list.reordered.connect(ctl.store.reorder)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(self._list)
        bl.addWidget(scroll, 1)
        # preview: shows exactly what 填入 / 仅引用 would paste
        self._preview_box = QWidget()
        pvl = QVBoxLayout(self._preview_box)
        pvl.setContentsMargins(10, 0, 10, 0)
        pvl.setSpacing(4)
        modes = QHBoxLayout()
        modes.addWidget(QLabel('将要填入：', objectName='faint'))
        self._pv_full = self._segment('完整', '与「填入」相同：提示语 + 每条批注的类型说明')
        self._pv_plain = self._segment('仅引用', '与「仅引用」相同：只有引用和批注')
        for b in (self._pv_full, self._pv_plain):
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, plain=b is self._pv_plain: self._set_preview_mode(plain))
            modes.addWidget(b)
        modes.addStretch(1)
        pvl.addLayout(modes)
        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setFixedHeight(150)
        self._preview.setPlaceholderText('没有勾选的批注。勾选上方卡片（已发送的也可以重新勾选）后，这里显示将要填入的内容。')
        pvl.addWidget(self._preview)
        self._preview_box.hide()
        self._preview_plain = False
        self._set_preview_mode(False)
        bl.addWidget(self._preview_box)
        foot = QHBoxLayout()
        foot.setContentsMargins(10, 4, 4, 8)
        foot.setSpacing(6)
        self._preview_btn = QPushButton('预览')
        self._preview_btn.setCheckable(True)
        self._preview_btn.toggled.connect(self._toggle_preview)
        self._plain_btn = QPushButton('仅引用')
        self._plain_btn.setToolTip('只填入引用和批注，不加提示语和类型说明')
        self._plain_btn.clicked.connect(lambda: ctl.fill(plain=True))
        self._fill_btn = QPushButton('填入', objectName='primary')
        self._fill_btn.setToolTip('填入完整 prompt（提示语 + 每条批注的类型说明）')
        self._fill_btn.clicked.connect(lambda: ctl.fill())
        foot.addWidget(self._preview_btn)
        foot.addStretch(1)
        foot.addWidget(self._plain_btn)
        foot.addWidget(self._fill_btn)
        foot.addWidget(QSizeGrip(self), 0, Qt.AlignBottom | Qt.AlignRight)
        bl.addLayout(foot)
        lay.addWidget(self._body, 1)

        # Translucent while idle so it doesn't hide what's behind it; solid while hovered/focused/just updated.
        self._fade = QPropertyAnimation(self, b'windowOpacity', self)
        self._fade.setDuration(160)
        self.update_opacity(animate=False)
        self._restore_geometry()

    def _tool(self, name: str, tip: str) -> QToolButton:
        b = QToolButton()
        ic = icon(name, C['muted'], C['text'])
        if name == 'pin':                         # checked = pinned: drawn in the accent color
            ic.addPixmap(pixmap(name, C['accent']), QIcon.Normal, QIcon.On)
            ic.addPixmap(pixmap(name, C['accent']), QIcon.Active, QIcon.On)
        b.setIcon(ic)
        b.setToolTip(tip)
        b.setCursor(Qt.ArrowCursor)
        return b

    def _segment(self, text: str, tip: str) -> QToolButton:
        b = QToolButton(objectName='segment')
        b.setText(text)
        b.setToolTip(tip)
        return b

    # ---- data ---------------------------------------------------------------------------------------------
    def refresh(self) -> None:
        items = self.ctl.store.all()
        types = self.ctl.cfg.type_map
        # filter box: all + one entry per source group
        groups: dict[str, tuple[str, int]] = {}
        for a in items:
            label, n = groups.get(a.group_key, (source_label(a.source, 34), 0))
            groups[a.group_key] = (source_label(a.source, 34), n + (a.status == PENDING))
        self._filter_box.blockSignals(True)
        self._filter_box.clear()
        self._filter_box.addItem(f'全部来源 · {sum(a.status == PENDING for a in items)} 条待发送', '')
        for key, (label, n) in groups.items():
            self._filter_box.addItem(f'{label} · {n}', key)
        idx = self._filter_box.findData(self._filter)
        if idx < 0:
            self._filter = ''
            idx = 0
        self._filter_box.setCurrentIndex(idx)
        self._filter_box.blockSignals(False)

        shown = self.visible_items(items)
        fallback = AnnoType(id='?', name='未知类型')
        cards = [Card(a, types.get(a.type_id) or fallback, self) for a in shown]
        empty = None
        if not cards:
            hk = self.ctl.cfg.data['hotkeys'].get('menu') or '快捷键'
            empty = QWidget()
            el = QVBoxLayout(empty)
            el.setContentsMargins(0, 28, 0, 0)
            pic = QLabel()
            pic.setPixmap(pixmap('note', C['faint'], 28))
            pic.setAlignment(Qt.AlignCenter)
            text = QLabel(f'在任意 Agent 窗口中选中文字，\n按 {hk} 或点划词按钮添加批注', objectName='empty')
            text.setAlignment(Qt.AlignCenter)
            el.addWidget(pic)
            el.addWidget(text)
        self._list.set_widgets(cards, empty)
        self.update_locate_states()
        toggle = self.ctl.cfg.data['hotkeys'].get('toggle_panel')
        self._close_btn.setToolTip(f'隐藏（{toggle} 重新显示）' if toggle else '隐藏')
        pending = sum(a.status == PENDING for a in items)
        self._count.setText(f'{pending} 条待发送')
        self._count.setVisible(bool(pending))
        if self._collapsed:
            self._fit_bar()
        n = len(self.fill_items(items))
        hk = self.ctl.cfg.data['hotkeys']
        fill_key = f"  {short_hotkey(hk['fill'])}" if hk.get('fill') else ''
        plain_key = f"  {short_hotkey(hk['fill_plain'])}" if hk.get('fill_plain') else ''
        self._fill_btn.setEnabled(n > 0)
        self._plain_btn.setEnabled(n > 0)
        self._fill_btn.setText((f'填入 {n} 条' if n else '填入') + fill_key)
        self._plain_btn.setText('仅引用' + plain_key)
        here = f"；{hk['fill_here']}：同样的内容输入在当前窗口的光标处" if hk.get('fill_here') else ''
        self._fill_btn.setToolTip('填入完整 prompt（提示语 + 每条批注的类型说明）' + here)
        self._update_preview(items)

    # ---- original-text highlights ---------------------------------------------------------------------------
    def _highlighter(self):
        return getattr(self.ctl, 'highlighter', None)

    def hover(self, ann_id: str | None) -> None:
        if self._highlighter():
            self._highlighter().set_hover(ann_id)

    def jump(self, ann: Annotation) -> None:
        if self._highlighter():
            self._highlighter().jump(ann)

    def update_locate_states(self) -> None:
        states = self._highlighter().states if self._highlighter() else {}
        for c in self._list._cards:
            c.set_locate_state(states.get(c.ann.id))

    def _sync_menu(self) -> None:
        h = self._highlighter()
        self._hl_action.blockSignals(True)
        self._hl_action.setChecked(bool(h and h.enabled()))
        self._hl_action.setEnabled(bool(h and h.settings.get('enabled', True)))
        self._hl_action.blockSignals(False)
        bubble_on = getattr(self.ctl, 'bubble_enabled', None)
        self._bubble_action.blockSignals(True)
        self._bubble_action.setChecked(bool(bubble_on and bubble_on()))
        self._bubble_action.setEnabled(bool(bubble_on and self.ctl.cfg.data.get('bubble', {}).get('enabled', True)))
        self._bubble_action.blockSignals(False)

    def _toggle_highlight(self, on: bool) -> None:
        if self._highlighter():
            self._highlighter().set_enabled(on)

    def visible_items(self, items: list[Annotation] | None = None) -> list[Annotation]:
        items = self.ctl.store.all() if items is None else items
        return [a for a in items if not self._filter or a.group_key == self._filter]

    def prompt_items(self, items: list[Annotation] | None = None) -> list[Annotation]:
        """The list shows newest first; the prompt numbers them bottom-up, i.e. in the order they were added."""
        return list(reversed(self.fill_items(items)))

    def fill_items(self, items: list[Annotation] | None = None) -> list[Annotation]:
        return [a for a in self.visible_items(items) if a.checked]   # sent ones too, if re-checked

    def _on_filter(self, idx: int) -> None:
        self._filter = self._filter_box.itemData(idx) or ''
        self.refresh()

    def _toggle_preview(self, on: bool) -> None:
        self._preview_box.setVisible(on)
        self._update_preview()

    def _set_preview_mode(self, plain: bool) -> None:
        self._preview_plain = plain
        self._pv_full.setChecked(not plain)
        self._pv_plain.setChecked(plain)
        self._update_preview()

    def _update_preview(self, items: list[Annotation] | None = None) -> None:
        if not self._preview_box.isVisible():
            return
        chosen = self.prompt_items(items)
        self._preview.setPlainText(self.ctl.compose(chosen, plain=self._preview_plain) if chosen else '')

    # ---- delete / clear -------------------------------------------------------------------------------------
    def _fill_trash_menu(self) -> None:
        """Built on open so the counts are current; everything applies to the current source filter."""
        m = self._trash_menu
        m.clear()
        shown = self.visible_items()
        checked = [a for a in shown if a.checked]
        sent = [a for a in shown if a.status == SENT]
        done = [a for a in shown if a.status == RESOLVED]
        scope = '' if not self._filter else '（当前来源）'
        act = m.addAction(f'删除已勾选的 {len(checked)} 条', lambda: self.delete_items(checked))
        act.setEnabled(bool(checked))
        act = m.addAction(f'清空已发送的 {len(sent)} 条{scope}', lambda: self.delete_items(sent))
        act.setEnabled(bool(sent))
        act = m.addAction(f'清空已解决的 {len(done)} 条{scope}', lambda: self.delete_items(done))
        act.setEnabled(bool(done))
        m.addSeparator()
        act = m.addAction(f'清空全部 {len(shown)} 条{scope}…', lambda: self.delete_items(shown, confirm=True))
        act.setEnabled(bool(shown))

    def set_status(self, a: Annotation, status: str) -> None:
        """Pending items are checked for the next fill; sent and resolved ones are not."""
        self.ctl.store.set_status([a.id], status, checked=status == PENDING)

    def delete_items(self, items: list[Annotation], confirm: bool = False) -> bool:
        if not items:
            return False
        if confirm:
            box = QMessageBox(QMessageBox.Warning, '清空批注', f'确定删除这 {len(items)} 条批注？删除后无法恢复。',
                              QMessageBox.Yes | QMessageBox.Cancel, self)
            box.button(QMessageBox.Yes).setText('删除')
            box.button(QMessageBox.Cancel).setText('取消')
            if box.exec() != QMessageBox.Yes:
                return False
        self.ctl.store.delete([a.id for a in items])
        return True

    def edit(self, ann_id: str) -> None:
        a = self.ctl.store.get(ann_id)
        if a is None:
            return
        dlg = EditDialog(a, self.ctl.cfg.types, self)
        if dlg.exec() == QDialog.Accepted:
            self.ctl.store.update(a.id, type_id=dlg.type.currentData(), comment=dlg.comment.toPlainText().strip())

    def reveal(self) -> None:
        """Make sure a newly added annotation is visible; a collapsed bar just updates its count."""
        if not self.isVisible():
            self.show_panel()

    # ---- auto-collapse --------------------------------------------------------------------------------------
    # Idle: a small see-through bar with the count. The pointer coming within `expand_distance` px of the bar
    # expands it; going farther than that from the full panel collapses it again (same margin both ways, so it
    # can't flicker at the edge). Our own menus/dialogs keep it open.
    POLL_MS = 80

    def _auto(self) -> bool:
        return bool(self.ctl.cfg.panel.get('auto_collapse', True)) and not self._pinned

    def _pointer(self) -> QPoint:
        return QCursor.pos()

    def _near(self, margin: int | None = None) -> bool:
        m = int(self.ctl.cfg.panel.get('expand_distance', 40)) if margin is None else margin
        return self.frameGeometry().adjusted(-m, -m, m, m).contains(self._pointer())

    def _cursor_inside(self) -> bool:
        return self._near(0)

    def _busy_ui(self) -> bool:
        return QApplication.activePopupWidget() is not None or QApplication.activeModalWidget() is not None

    def _track_pointer(self) -> None:
        if not self.isVisible() or not self._auto():
            self._poller.stop()
            return
        near = self._near()
        if self._collapsed and near:
            self.set_collapsed(False)
        elif not self._collapsed and not near and not self._busy_ui() and time.monotonic() >= self._grace_until:
            self.set_collapsed(True)

    def _sync_poller(self) -> None:
        if self.isVisible() and self._auto():
            self._poller.start()
        else:
            self._poller.stop()

    def set_collapsed(self, on: bool) -> None:
        if on == self._collapsed:
            return
        if on:
            self._expanded_geo = self.geometry()
            self._body.hide()
            self.setMinimumSize(0, 0)
            self._fit_bar()
        else:
            self.setMinimumSize(*min_size())
            self.setMaximumSize(16777215, 16777215)
            self._body.show()
            self.setGeometry(self._expanded_geo)
        # The window manager may still report the old size for a moment (seen: the collapsed bar's size
        # clamped to the minimum got saved as the panel size, leaving no room for the list): don't save
        # sizes from that window, and re-apply the expanded size once it has settled.
        self._settle_until = time.monotonic() + 0.5
        QTimer.singleShot(250, self._settle)
        self._collapsed = on
        self.update_opacity(animate=False)
        self._save_timer.start()

    def _fit_bar(self) -> None:
        """Size the collapsed bar to its header (the count in it changes), keeping the panel's right edge."""
        self._header.layout().activate()
        w = max(self._header.sizeHint().width() + 8, 200) + 2 * margin()
        h = self._header.sizeHint().height() + 2 + 2 * margin()
        self.setFixedSize(w, h)
        self.move(self._expanded_geo.right() - w + 1, self._expanded_geo.y())

    def _settle(self) -> None:
        if not self._collapsed and self.size() != self._expanded_geo.size():
            self.setGeometry(self._expanded_geo)

    def set_pinned(self, on: bool) -> None:
        self._pinned = on
        if self._pin_btn.isChecked() != on:
            self._pin_btn.setChecked(on)
        if on:
            self.set_collapsed(False)
        self._sync_poller()
        self.update_opacity()
        self._save_timer.start()

    def config_changed(self) -> None:
        if not self._auto():
            self.set_collapsed(False)
        self._sync_poller()
        self.update_opacity(animate=False)

    # ---- opacity ------------------------------------------------------------------------------------------
    def target_opacity(self) -> float:
        p = self.ctl.cfg.panel
        if p.get('auto_collapse', True):
            solid = not self._collapsed
        else:
            solid = self._cursor_inside() or self.isActiveWindow()
        value = p.get('opacity', 0.96) if solid else p.get('idle_opacity', 0.5)
        return min(1.0, max(0.15, float(value)))

    def update_opacity(self, animate: bool = True) -> None:
        target = self.target_opacity()
        self._fade.stop()
        if animate and self.isVisible():
            self._fade.setStartValue(self.windowOpacity())
            self._fade.setEndValue(target)
            self._fade.start()
        else:
            self.setWindowOpacity(target)

    def enterEvent(self, e) -> None:
        if self._collapsed:
            self.set_collapsed(False)
        self.update_opacity()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self.update_opacity()
        self.hover(None)            # a card rebuilt under the mouse never gets its leave event
        super().leaveEvent(e)

    def changeEvent(self, e) -> None:
        if e.type() == QEvent.ActivationChange:
            self.update_opacity()
        super().changeEvent(e)

    def hideEvent(self, e) -> None:
        self._poller.stop()
        super().hideEvent(e)

    # ---- window behaviour -----------------------------------------------------------------------------------
    def show_panel(self) -> None:
        self.show()
        self.raise_()
        self._grace_until = time.monotonic() + 1.5    # let the user see it appear before it tucks away
        self._sync_poller()

    def toggle(self) -> None:
        self.hide() if self.isVisible() else self.show_panel()

    def _on_header(self, e) -> bool:
        return self._header.rect().contains(self._header.mapFrom(self, e.position().toPoint()))

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton and self._on_header(e):
            if self.windowHandle() and self.windowHandle().startSystemMove():
                return
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e) -> None:
        if self._on_header(e):
            self.set_pinned(not self._pinned)

    def moveEvent(self, e) -> None:
        if self._collapsed:   # dragging the bar moves where the full panel will open (right-aligned)
            g = self._expanded_geo
            self._expanded_geo = QRect(self.x() + self.width() - g.width(), self.y(), g.width(), g.height())
        self._save_timer.start()
        super().moveEvent(e)

    def resizeEvent(self, e) -> None:
        if time.monotonic() >= self._settle_until:
            self._save_timer.start()
        super().resizeEvent(e)

    def _restore_geometry(self) -> None:
        st = self.ctl.state.get('panel', {})
        screen = QGuiApplication.primaryScreen().availableGeometry()
        w, h = st.get('w', 380), st.get('h', 560)
        if w < min_size()[0] or h < min_size()[1]:  # a broken saved size would hide the list
            w, h = max(w, 380), 560
        x, y = st.get('x', screen.right() - w - 24), st.get('y', screen.top() + 120)
        if not screen.intersects(QRect(x, y, w, h)):
            x, y = screen.right() - w - 24, screen.top() + 120
        self.setGeometry(x, y, w, h)
        self._expanded_geo = QRect(x, y, w, h)

    def _save_geometry(self) -> None:
        if time.monotonic() < self._settle_until:
            self._save_timer.start()
            return
        g = self._expanded_geo if self._collapsed else self.geometry()   # always remember the full panel
        self.ctl.state['panel'] = {'x': g.x(), 'y': g.y(), 'w': g.width(), 'h': g.height(),
                                   'pinned': self._pinned}
        self.ctl.save_state()
