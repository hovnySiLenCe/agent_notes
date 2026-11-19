"""The panel's 计划 tab: the plans agents report, one per project, by category (进行中 / 等你决定 / 以后 …).

Clicking an item shows the same row of type buttons as selecting text does; the annotation made on it joins the
annotation list and is filled back into the agent's window like any other (or typed at the cursor, Alt+Return).
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton,
                               QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from ..core.models import PENDING, RESOLVED, SENT
from ..core.plans import DONE, to_text
from .bubble import SelectionBubble
from .icons import icon, pixmap
from .theme import C, type_tag_style

if TYPE_CHECKING:
    from ..app import Controller

DONE_SHOWN = 10


def _ago(t: float) -> str:
    d = time.time() - t
    if d < 60:
        return '刚刚'
    if d < 3600:
        return f'{int(d // 60)} 分钟前'
    if d < 86400 and time.localtime(t).tm_yday == time.localtime().tm_yday:
        return time.strftime('%H:%M', time.localtime(t))
    return time.strftime('%m-%d %H:%M', time.localtime(t))


class PlanItem(QFrame):
    def __init__(self, item: dict, view: 'PlanView', tags: list[tuple[str, str, str]], done: bool = False):
        super().__init__(objectName='planItem')
        self.item, self.view = item, view
        self.setProperty('done', done)
        self.setCursor(Qt.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 8, 7)
        lay.setSpacing(4)
        text = QLabel(item['text'], objectName='planText')
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.NoTextInteraction)
        text.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(text)
        if tags:
            row = QHBoxLayout()
            row.setSpacing(5)
            for name, color, status in tags:
                t = QLabel(name + (' ✓' if status == SENT else ''))
                t.setStyleSheet(type_tag_style(color))
                t.setToolTip('已批注' + ('，已发送' if status == SENT else '，待发送'))
                row.addWidget(t)
            row.addStretch(1)
            lay.addLayout(row)
        self.setToolTip('点击：加批注（和划词一样选类型）；右键：更多')

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.view.pick(self.item['id'])
        super().mouseReleaseEvent(e)

    def contextMenuEvent(self, e) -> None:
        m = QMenu(self)
        m.addAction('批注…', lambda: self.view.ctl.annotate_plan_item(self.item['id'], None))
        m.addAction('复制文本', lambda: QGuiApplication.clipboard().setText(self.item['text']))
        if self.item['status'] == DONE:
            m.addAction('移回计划', lambda: self.view.ctl.plans.set_status(self.item['id'], 'active'))
        else:
            m.addAction('标记为已完成', lambda: self.view.ctl.plans.set_status(self.item['id'], DONE))
        m.exec(e.globalPos())


class PlanView(QWidget):
    def __init__(self, ctl: 'Controller'):
        super().__init__()
        self.ctl = ctl
        self._project = ctl.state.get('plan_project', '')
        self._show_done = False
        self._picked: str | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        top = QHBoxLayout()
        top.setContentsMargins(10, 0, 6, 0)
        top.setSpacing(4)
        self.projects = QComboBox()
        self.projects.currentIndexChanged.connect(self._on_project)
        top.addWidget(self.projects, 1)
        self.more = QToolButton()
        self.more.setIcon(icon('more', C['muted'], C['text']))
        self.more.setToolTip('计划菜单')
        self.more.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self)
        menu.addAction('复制整个计划', self._copy)
        menu.addAction('删除这个项目的计划…', self._delete)
        menu.addSeparator()
        menu.addAction('如何让 Agent 发送计划', self._show_help)
        self.more.setMenu(menu)
        top.addWidget(self.more)
        lay.addLayout(top)
        self.meta = QLabel(objectName='faint')
        self.meta.setContentsMargins(12, 0, 10, 0)
        lay.addWidget(self.meta)
        self._list = QWidget()
        self._lay = QVBoxLayout(self._list)
        self._lay.setContentsMargins(10, 2, 10, 10)
        self._lay.setSpacing(5)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setWidget(self._list)
        lay.addWidget(self.scroll, 1)
        foot = QHBoxLayout()
        foot.setContentsMargins(10, 4, 4, 8)
        self.hint = QLabel('点条目加批注，批注会出现在「批注」里', objectName='faint')
        self.hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.fill_btn = QPushButton('填入', objectName='primary')
        self.fill_btn.clicked.connect(lambda: ctl.fill())
        foot.addWidget(self.hint, 1)
        foot.addWidget(self.fill_btn)
        self.foot = foot
        lay.addLayout(foot)
        self.bubble = SelectionBubble()
        self.bubble.chosen.connect(self._chosen)

    # ---- data -----------------------------------------------------------------------------------------------
    def refresh(self, select: str | None = None) -> None:
        if select:
            self._project = select
        plans = self.ctl.plans
        projects = plans.projects()
        self.projects.blockSignals(True)
        self.projects.clear()
        for p in projects:
            n = len(plans.items(p['name']))
            self.projects.addItem(f'{p["name"]} · {n} 条', p['name'])
        idx = self.projects.findData(self._project)
        if idx < 0 and projects:
            idx, self._project = 0, projects[0]['name']
        self.projects.setCurrentIndex(max(idx, 0))
        self.projects.blockSignals(False)
        self.projects.setVisible(bool(projects))
        self.more.setVisible(bool(projects))
        bar = self.scroll.verticalScrollBar()
        keep = bar.value() if not select else 0
        while self._lay.count():
            it = self._lay.takeAt(0)
            if it.widget() is not None:
                it.widget().deleteLater()
        proj = plans.project(self._project) if projects else None
        if proj is None:
            self.meta.hide()
            self._empty()
        else:
            src = proj['source'] or {}
            where = (src.get('title') or '')[:40]
            ago = _ago(proj['updated_at'])
            self.meta.setText((f'{ago}更新' if ago == '刚刚' else f'{ago} 更新') + (f' · {where}' if where else ''))
            self.meta.setToolTip(f'来源窗口：{src.get("title") or "未知"}\n目录：{src.get("cwd") or "未知"}')
            self.meta.show()
            tags = self._tags()
            for cat, items in plans.sections(self._project):
                head = QLabel(f'{cat or "其他"}  <span style="color:{C["faint"]}">{len(items)}</span>',
                              objectName='planSection')
                self._lay.addWidget(head)
                for it in items:
                    self._lay.addWidget(PlanItem(it, self, tags.get(it['id'], [])))
            done = plans.items(self._project, DONE)
            if done:
                tog = QToolButton(objectName='segment')
                tog.setText(('▾ ' if self._show_done else '▸ ') + f'已完成 / 已移除  {len(done)}')
                tog.setToolTip('Agent 新发来的计划里已经没有的条目')
                tog.clicked.connect(self._toggle_done)
                self._lay.addWidget(tog, 0, Qt.AlignLeft)
                if self._show_done:
                    for it in done[:DONE_SHOWN]:
                        self._lay.addWidget(PlanItem(it, self, tags.get(it['id'], []), done=True))
        self._lay.addStretch(1)
        self._list.layout().activate()
        bar.setValue(keep)
        n = len(self.ctl.panel.fill_items()) if getattr(self.ctl, 'panel', None) is not None else 0
        self.fill_btn.setEnabled(n > 0)
        self.fill_btn.setText(f'填入 {n} 条' if n else '填入')

    def _tags(self) -> dict[str, list[tuple[str, str, str]]]:
        """Plan item id -> the annotations made on it (type name, color, status)."""
        out: dict[str, list] = {}
        types = self.ctl.cfg.type_map
        for a in self.ctl.store.all():
            if a.anchor.get('method') == 'plan' and a.status in (PENDING, SENT) and a.anchor.get('item'):
                t = types.get(a.type_id)
                out.setdefault(a.anchor['item'], []).append((t.name if t else a.type_id, t.color if t else C['faint'],
                                                             a.status))
        return out

    def _empty(self) -> None:
        port = self.ctl.plan_server.port() if getattr(self.ctl, 'plan_server', None) else 0
        pic = QLabel()
        pic.setPixmap(pixmap('note', C['faint'], 28))
        pic.setAlignment(Qt.AlignCenter)
        text = QLabel(self._help_text(port), objectName='empty')
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._lay.addSpacing(18)
        self._lay.addWidget(pic)
        self._lay.addWidget(text)

    @staticmethod
    def _help_text(port: int) -> str:
        http = (f'其他 Agent：把计划文本 POST 到\nhttp://127.0.0.1:{port}/plan/项目名' if port else
                '其他 Agent：./run.sh --plan 项目名 < 计划.md')
        return ('还没有收到 Agent 的计划。\n\n'
                'Claude Code：运行一次 ./run.sh --install-claude-hook，\n之后每次回复末尾的「计划」会自动出现在这里。\n\n'
                + http)

    # ---- actions --------------------------------------------------------------------------------------------
    def pick(self, item_id: str) -> None:
        """An item was clicked: offer the annotation types next to the pointer."""
        self._picked = item_id
        conf = self.ctl.cfg.data.get('bubble', {})
        n = max(0, min(9, int(conf.get('types', 4))))
        hk = self.ctl.cfg.data['hotkeys']
        self.bubble.set_types(self.ctl.cfg.types[:n], {**{t.id: t.hotkey for t in self.ctl.cfg.types},
                                                       '': hk.get('menu', '')})
        self.bubble.timeout_ms = 6000
        self.bubble.show_at(QCursor.pos())

    def _chosen(self, type_id: str) -> None:
        if self._picked:
            self.ctl.annotate_plan_item(self._picked, type_id or None)

    def _on_project(self, idx: int) -> None:
        self._project = self.projects.itemData(idx) or ''
        self.ctl.state['plan_project'] = self._project
        self.refresh()

    def _toggle_done(self) -> None:
        self._show_done = not self._show_done
        self.refresh()

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(to_text(self.ctl.plans.sections(self._project)))

    def _delete(self) -> None:
        if QMessageBox.question(self, '删除计划', f'删除项目「{self._project}」的计划？（已做的批注保留）') \
                == QMessageBox.Yes:
            self.ctl.plans.delete_project(self._project)
            self._project = ''
            self.refresh()

    def _show_help(self) -> None:
        port = self.ctl.plan_server.port() if getattr(self.ctl, 'plan_server', None) else 0
        QMessageBox.information(self, '让 Agent 发送计划', self._help_text(port).replace('还没有收到 Agent 的计划。\n\n', '')
                                + '\n\n计划按「进行中 / 等你决定 / 以后」这类分类行分组，每行或每个 “- ” 开头的行是一条。'
                                  '同一项目再次发送时整体替换，消失的条目移到「已完成」。')

    def hide_transient(self) -> None:
        self.bubble.hide()
