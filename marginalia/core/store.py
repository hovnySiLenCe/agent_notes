"""SQLite persistence for annotations. Used from the Qt main thread only."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Callable, Iterable

from .models import Annotation

_SCHEMA = """
CREATE TABLE IF NOT EXISTS annotations (
    id          TEXT PRIMARY KEY,
    type_id     TEXT NOT NULL,
    quote       TEXT NOT NULL,
    comment     TEXT NOT NULL DEFAULT '',
    anchor      TEXT NOT NULL DEFAULT '{}',
    source      TEXT NOT NULL DEFAULT '{}',
    status      TEXT NOT NULL,
    checked     INTEGER NOT NULL DEFAULT 1,
    created_at  REAL NOT NULL,
    sort_order  INTEGER NOT NULL
)"""

_COLUMNS = {'type_id': 'type_id', 'quote': 'quote', 'comment': 'comment', 'anchor': 'anchor',
            'source': 'source', 'status': 'status', 'checked': 'checked', 'order': 'sort_order'}


def _to_row(a: Annotation) -> tuple:
    return (a.id, a.type_id, a.quote, a.comment, json.dumps(a.anchor, ensure_ascii=False),
            json.dumps(a.source, ensure_ascii=False), a.status, int(a.checked), a.created_at, a.order)


def _from_row(r: sqlite3.Row) -> Annotation:
    return Annotation(id=r['id'], type_id=r['type_id'], quote=r['quote'], comment=r['comment'],
                      anchor=json.loads(r['anchor']), source=json.loads(r['source']), status=r['status'],
                      checked=bool(r['checked']), created_at=r['created_at'], order=r['sort_order'])


class Store:
    def __init__(self, path: Path | str):
        self._db = sqlite3.connect(str(path))
        self._db.row_factory = sqlite3.Row
        self._db.execute(_SCHEMA)
        self._db.commit()
        self._listeners: list[Callable[[], None]] = []

    def subscribe(self, fn: Callable[[], None]) -> None:
        self._listeners.append(fn)

    def _commit(self) -> None:
        self._db.commit()
        for fn in self._listeners:
            fn()

    def add(self, a: Annotation) -> Annotation:
        """New annotations go to the top: display order is newest first (sort_order ascending)."""
        a.order = self._db.execute('SELECT COALESCE(MIN(sort_order), 1) - 1 FROM annotations').fetchone()[0]
        self._db.execute('INSERT INTO annotations VALUES (?,?,?,?,?,?,?,?,?,?)', _to_row(a))
        self._commit()
        return a

    def get(self, ann_id: str) -> Annotation | None:
        r = self._db.execute('SELECT * FROM annotations WHERE id = ?', (ann_id,)).fetchone()
        return _from_row(r) if r else None

    def all(self) -> list[Annotation]:
        return [_from_row(r) for r in self._db.execute('SELECT * FROM annotations ORDER BY sort_order')]

    def update(self, ann_id: str, **changes) -> None:
        sets, vals = [], []
        for k, v in changes.items():
            col = _COLUMNS[k]
            if k in ('anchor', 'source'):
                v = json.dumps(v, ensure_ascii=False)
            elif k == 'checked':
                v = int(v)
            sets.append(f'{col} = ?')
            vals.append(v)
        if sets:
            self._db.execute(f"UPDATE annotations SET {', '.join(sets)} WHERE id = ?", (*vals, ann_id))
            self._commit()

    def set_status(self, ids: Iterable[str], status: str, checked: bool | None = None) -> None:
        for i in ids:
            if checked is None:
                self._db.execute('UPDATE annotations SET status = ? WHERE id = ?', (status, i))
            else:
                self._db.execute('UPDATE annotations SET status = ?, checked = ? WHERE id = ?',
                                 (status, int(checked), i))
        self._commit()

    def delete(self, ids: Iterable[str]) -> None:
        self._db.executemany('DELETE FROM annotations WHERE id = ?', [(i,) for i in ids])
        self._commit()

    def delete_status(self, status: str) -> None:
        self._db.execute('DELETE FROM annotations WHERE status = ?', (status,))
        self._commit()

    def sort_newest_first(self) -> None:
        self.reorder([a.id for a in sorted(self.all(), key=lambda a: a.created_at, reverse=True)])

    def reorder(self, ids: list[str]) -> None:
        """Rewrite sort order so that `ids` appear in the given order (others keep their relative order)."""
        rest = [a.id for a in self.all() if a.id not in set(ids)]
        for n, i in enumerate(ids + rest):
            self._db.execute('UPDATE annotations SET sort_order = ? WHERE id = ?', (n, i))
        self._commit()
