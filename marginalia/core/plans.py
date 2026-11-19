"""Agents' plan lists: parsing what they report, and keeping one plan per project (no Qt / platform code).

An agent ends its replies with a plan recap such as

    计划
    **进行中**
    - v2 训练：预计 11-21 凌晨完成
    **等你决定**
    - 两个训练脚本的新选项要不要提交
    以后
    训练跑完后停掉内存记录服务

It reaches Marginalia as text (from a Claude Code hook, the command line or a local HTTP request) and replaces
the project's plan. Items are matched with the previous snapshot by their text (small edits still match), so
an item keeps its id, and the annotations made on it, across updates; items that disappear are kept a while as
done.
"""
from __future__ import annotations

import difflib
import json
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Callable

ACTIVE, DONE = 'active', 'done'
KEEP_DONE = 30                 # done items kept per project
SIMILAR = 0.72                 # text similarity at which an edited item still counts as the same one
MAX_ITEMS = 300

_HEADING = re.compile(r'^\s*(?:#{1,6}\s*)?(?:\*\*|__)?\s*(计划|plan|plans|todo|待办)\s*(?:\*\*|__)?\s*[:：]?\s*$', re.I)
_BULLET = re.compile(r'^(\s*)(?:[-*+•·▪◦]|\d{1,3}[.)、]|[（(]\d{1,3}[)）])\s+')
_CATEGORY_WORDS = ('进行中', '正在进行', '等你', '等待', '待确认', '待你', '需要你', '以后', '之后', '稍后', '后续',
                   '已完成', '完成', '下一步', '阻塞', 'in progress', 'doing', 'waiting', 'blocked', 'later',
                   'next', 'done', 'todo', 'backlog')


def _strip_marks(line: str) -> tuple[str, bool]:
    """Line without heading / bold markers; True when it had them (a markdown heading or a fully bold line)."""
    s = line.strip()
    marked = False
    m = re.match(r'^#{1,6}\s+(.*)$', s)
    if m:
        s, marked = m.group(1).strip(), True
    m = re.match(r'^(\*\*|__)(.+?)\1\s*[:：]?$', s)
    if m:
        s, marked = m.group(2).strip(), True
    return s.rstrip(':：').strip(), marked


def _is_category(line: str) -> str | None:
    if _BULLET.match(line):
        return None
    name, marked = _strip_marks(line)
    if not name or len(name) > 24:
        return None
    low = name.lower()
    if marked or any(low.startswith(w) for w in _CATEGORY_WORDS) or re.search(r'[:：]\s*$', line.strip()):
        return name
    return None


def _clean(text: str) -> str:
    return re.sub(r'\*\*(.+?)\*\*', r'\1', text).strip()


def parse(text: str) -> list[tuple[str, list[str]]]:
    """[(category, [item text])] in their order. Bulleted lines start items, indented lines under an item
    (sub-bullets, wrapped text) belong to it; plain lines are items of their own."""
    sections: list[tuple[str, list[str]]] = []
    lines = text.replace('\r\n', '\n').split('\n')
    if lines and _HEADING.match(lines[0] or ''):
        lines = lines[1:]
    current: list[str] | None = None
    last_indent = 0
    for raw in lines:
        if not raw.strip() or re.fullmatch(r'\s*(-{3,}|\*{3,}|_{3,})\s*', raw):
            continue
        if _HEADING.match(raw):
            continue
        cat = _is_category(raw)
        if cat is not None:
            current = []
            sections.append((cat, current))
            continue
        if current is None:
            current = []
            sections.append(('', current))
        m = _BULLET.match(raw)
        indent = len(raw) - len(raw.lstrip())
        if m:
            body = _clean(raw[m.end():])
            if current and indent > last_indent:
                current[-1] += '\n· ' + body           # a sub-item (indented under the previous item)
                continue
            current.append(body)
            last_indent = indent
        elif current and indent > last_indent:
            current[-1] += ' ' + _clean(raw)          # wrapped continuation
        else:
            current.append(_clean(raw))
            last_indent = indent
    return [(c, items[:MAX_ITEMS]) for c, items in sections if items or c]


def extract(message: str) -> str | None:
    """The plan section at the end of an agent's reply (after its last 计划 / Plan heading), or None."""
    lines = message.replace('\r\n', '\n').split('\n')
    for i in range(len(lines) - 1, -1, -1):
        if _HEADING.match(lines[i]):
            body = '\n'.join(lines[i + 1:]).strip()
            return body or None
    return None


def to_text(sections: list[tuple[str, list[dict]]]) -> str:
    out = []
    for cat, items in sections:
        if cat:
            out.append(cat)
        out += [f'- {it["text"]}' for it in items]
    return '\n'.join(out)


_SCHEMA = ["""
CREATE TABLE IF NOT EXISTS plan_projects (
    name        TEXT PRIMARY KEY,
    source      TEXT NOT NULL DEFAULT '{}',
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
)""", """
CREATE TABLE IF NOT EXISTS plan_items (
    id          TEXT PRIMARY KEY,
    project     TEXT NOT NULL,
    category    TEXT NOT NULL,
    text        TEXT NOT NULL,
    position    INTEGER NOT NULL,
    status      TEXT NOT NULL,
    first_seen  REAL NOT NULL,
    updated_at  REAL NOT NULL
)"""]


class PlanStore:
    """Plans by project in the notes database. Main thread only."""

    def __init__(self, path: Path | str):
        self._db = sqlite3.connect(str(path))
        self._db.row_factory = sqlite3.Row
        for sql in _SCHEMA:
            self._db.execute(sql)
        self._db.commit()
        self._listeners: list[Callable[[], None]] = []

    def subscribe(self, fn: Callable[[], None]) -> None:
        self._listeners.append(fn)

    def _commit(self) -> None:
        self._db.commit()
        for fn in self._listeners:
            fn()

    # ---- reading --------------------------------------------------------------------------------------------
    def projects(self) -> list[dict]:
        """Most recently updated first."""
        rows = self._db.execute('SELECT * FROM plan_projects ORDER BY updated_at DESC').fetchall()
        return [{'name': r['name'], 'source': json.loads(r['source']), 'updated_at': r['updated_at']} for r in rows]

    def project(self, name: str) -> dict | None:
        r = self._db.execute('SELECT * FROM plan_projects WHERE name = ?', (name,)).fetchone()
        return {'name': r['name'], 'source': json.loads(r['source']), 'updated_at': r['updated_at']} if r else None

    def items(self, project: str, status: str = ACTIVE) -> list[dict]:
        order = 'position' if status == ACTIVE else 'updated_at DESC'
        rows = self._db.execute(f'SELECT * FROM plan_items WHERE project = ? AND status = ? ORDER BY {order}',
                                (project, status)).fetchall()
        return [dict(r) for r in rows]

    def item(self, item_id: str) -> dict | None:
        r = self._db.execute('SELECT * FROM plan_items WHERE id = ?', (item_id,)).fetchone()
        return dict(r) if r else None

    def sections(self, project: str) -> list[tuple[str, list[dict]]]:
        out: list[tuple[str, list[dict]]] = []
        for it in self.items(project):
            if not out or out[-1][0] != it['category']:
                out.append((it['category'], []))
            out[-1][1].append(it)
        return out

    # ---- writing --------------------------------------------------------------------------------------------
    def update(self, project: str, sections: list[tuple[str, list[str]]], source: dict | None = None,
               category: str | None = None) -> dict:
        """Replace the project's plan (or only `category` of it) with `sections`. Returns counts
        {'added', 'removed', 'kept'}."""
        now = time.time()
        old = self.items(project)
        replaced = [it for it in old if category is None or it['category'] == category]
        others = [it for it in old if not (category is None or it['category'] == category)]
        new = [(cat, text) for cat, items in sections for text in items]
        if category is not None:
            new = [(category, text) for _, text in new]
        match: dict[int, dict] = {}
        free = list(replaced)
        for i, (cat, text) in enumerate(new):                       # same text (same category first)
            for it in sorted(free, key=lambda it: it['category'] != cat):
                if it['text'] == text:
                    match[i] = it
                    free.remove(it)
                    break
        for i, (cat, text) in enumerate(new):                       # then edited ones
            if i in match or not free:
                continue
            scored = [(difflib.SequenceMatcher(None, it['text'], text).ratio() + 0.05 * (it['category'] == cat), it)
                      for it in free]
            score, it = max(scored, key=lambda x: x[0])
            if score >= SIMILAR:
                match[i] = it
                free.remove(it)
        ordered: list[tuple[str, str, dict | None]] = [(c, t, match.get(i)) for i, (c, t) in enumerate(new)]
        if category is not None:                                     # keep the other categories where they were
            first = min((it['position'] for it in replaced), default=None)
            before = [it for it in others if first is None or it['position'] < first]
            after = [it for it in others if first is not None and it['position'] > first]
            if first is None:
                before, after = others, []
            ordered = [(it['category'], it['text'], it) for it in before] + ordered + \
                      [(it['category'], it['text'], it) for it in after]
        for pos, (cat, text, it) in enumerate(ordered):
            if it is None:
                self._db.execute('INSERT INTO plan_items VALUES (?,?,?,?,?,?,?,?)',
                                 (uuid.uuid4().hex[:12], project, cat, text, pos, ACTIVE, now, now))
            else:
                changed = (it['category'], it['text']) != (cat, text)
                self._db.execute('UPDATE plan_items SET category = ?, text = ?, position = ?, updated_at = ? '
                                 'WHERE id = ?', (cat, text, pos, now if changed else it['updated_at'], it['id']))
        for it in free:
            self._db.execute('UPDATE plan_items SET status = ?, updated_at = ? WHERE id = ?', (DONE, now, it['id']))
        self._db.execute('DELETE FROM plan_items WHERE project = ? AND status = ? AND id NOT IN '
                         '(SELECT id FROM plan_items WHERE project = ? AND status = ? ORDER BY updated_at DESC '
                         'LIMIT ?)', (project, DONE, project, DONE, KEEP_DONE))
        prev = self.project(project)
        src = json.dumps(source if source is not None else (prev or {}).get('source', {}), ensure_ascii=False)
        self._db.execute('INSERT INTO plan_projects VALUES (?,?,?,?) ON CONFLICT(name) DO UPDATE SET '
                         'source = excluded.source, updated_at = excluded.updated_at', (project, src, now, now))
        self._commit()
        return {'added': sum(it is None for _, _, it in ordered), 'removed': len(free),
                'kept': sum(it is not None for _, _, it in ordered) - len(others)}

    def set_source(self, project: str, source: dict) -> None:
        self._db.execute('UPDATE plan_projects SET source = ? WHERE name = ?',
                         (json.dumps(source, ensure_ascii=False), project))
        self._commit()

    def set_status(self, item_id: str, status: str) -> None:
        self._db.execute('UPDATE plan_items SET status = ?, updated_at = ? WHERE id = ?', (status, time.time(), item_id))
        self._commit()

    def delete_project(self, project: str) -> None:
        self._db.execute('DELETE FROM plan_items WHERE project = ?', (project,))
        self._db.execute('DELETE FROM plan_projects WHERE name = ?', (project,))
        self._commit()
