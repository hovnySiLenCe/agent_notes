"""Plain data types shared by every layer (no Qt / platform imports)."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, fields

PENDING = 'pending'
SENT = 'sent'

INPUT_NONE = 'none'          # save immediately, no comment box
INPUT_OPTIONAL = 'optional'
INPUT_REQUIRED = 'required'


@dataclass
class AnnoType:
    id: str
    name: str
    color: str = '#7C8594'
    hotkey: str = ''
    input: str = INPUT_OPTIONAL
    template: str = ''

    @classmethod
    def from_dict(cls, d: dict) -> 'AnnoType':
        names = {f.name for f in fields(cls)}
        t = cls(**{k: v for k, v in d.items() if k in names})
        if not t.id or not t.name:
            raise ValueError(f'批注类型缺少 id 或 name: {d}')
        if t.input not in (INPUT_NONE, INPUT_OPTIONAL, INPUT_REQUIRED):
            raise ValueError(f'批注类型 {t.id} 的 input 只能是 none/optional/required')
        return t


@dataclass
class Annotation:
    type_id: str
    quote: str
    comment: str = ''
    anchor: dict = field(default_factory=dict)   # where the quote lives (AT-SPI path/offsets, prefix/suffix)
    source: dict = field(default_factory=dict)   # which window/app/url it came from
    status: str = PENDING
    checked: bool = True
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: float = field(default_factory=time.time)
    order: int = 0

    @property
    def group_key(self) -> str:
        """Conversation grouping: page URL when known, otherwise the source window."""
        s = self.source
        return s.get('url') or f"{s.get('wm_class', '?')}:{s.get('xid', 0)}"
