"""Keep the on-screen rectangles of annotated text up to date while the user scrolls. Worker thread only.

Each tick costs two character-extent queries per located text segment: when they haven't moved, the cached
rectangles are reused; when both ends moved by the same offset (scrolling), the rectangles are shifted and only
the clipping is recomputed; anything else (reflow, resize) re-measures. The text is re-verified every few
seconds and located again when it changed.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..x11 import windows
from .geometry import EMPTY, Rect, intersect, text_rects, visible_area, vte_rects
from .locate import Segment, locate, scroll_into_view
from .tree import OBJ, Atspi, T

RETRY_AFTER = 3.0        # s before trying again to locate a quote that wasn't found
VERIFY_EVERY = 2.0       # s between checks that the located text is still the same
LOCATE_BUDGET = 0.6      # s of tree walking per locate; at most one locate per tick


@dataclass
class _Seg:
    seg: Segment
    probe: tuple | None = None
    raw: list[Rect] = field(default_factory=list)     # unclipped character-line rectangles
    clip: Rect | None = None                          # visible area of the containers (None = unknown)

    def rects(self) -> list[Rect]:
        if self.clip is None:
            return self.raw
        if self.clip == EMPTY:
            return []
        return [r for r in (intersect(r, self.clip) for r in self.raw) if r]


@dataclass
class _Entry:
    key: tuple
    segs: list[_Seg] | None          # None: not found
    since: float = 0.0               # when located / when the failed attempt was made
    verified_at: float = 0.0


def _ends(seg: Segment) -> tuple[int, int] | None:
    """Offsets of the first and last visible characters of the segment."""
    idx = [k for k, ch in enumerate(seg.text) if ch != OBJ and not ch.isspace()]
    return (seg.start + idx[0], seg.start + idx[-1]) if idx else None


def _probe(s: _Seg, xid: int) -> tuple | None:
    if s.seg.terminal:      # VTE: row position inside the widget + where the window is
        e = T.get_character_extents(s.seg.node, s.seg.start, Atspi.CoordType.WINDOW)
        return ('t', e.x, e.y, windows.client_rect(xid))
    ends = _ends(s.seg)
    if ends is None:
        return None
    a = T.get_character_extents(s.seg.node, ends[0], Atspi.CoordType.SCREEN)
    b = T.get_character_extents(s.seg.node, ends[1], Atspi.CoordType.SCREEN)
    return ('g', a.x, a.y, b.x, b.y)


def _refresh(s: _Seg, xid: int) -> None:
    p = _probe(s, xid)
    if p is None or p == s.probe:
        return
    old, s.probe = s.probe, p
    if s.seg.terminal:
        s.raw, s.clip = vte_rects(s.seg.node, xid, s.seg.start, s.seg.end), None
        return
    if old is not None and p[1] - old[1] == p[3] - old[3] and p[2] - old[2] == p[4] - old[4]:
        dx, dy = p[1] - old[1], p[2] - old[2]          # scrolled or window moved: same shape, new place
        s.raw = [(x + dx, y + dy, w, h) for x, y, w, h in s.raw]
    else:
        s.raw = text_rects(s.seg.node, s.seg.start, s.seg.end)
    s.clip = visible_area(s.seg.node)


class Tracker:
    def __init__(self, own_pid: int):
        self.own_pid = own_pid
        self.context_xid: int | None = None       # last active window that isn't one of ours
        self._entries: dict[str, _Entry] = {}

    def _verified(self, e: _Entry, now: float) -> bool:
        if now - e.verified_at < VERIFY_EVERY:
            return True
        try:
            ok = all(T.get_text(s.seg.node, s.seg.start, s.seg.end) == s.seg.text for s in e.segs or [])
        except Exception:
            ok = False
        e.verified_at = now
        return ok

    def _entry(self, req: dict, now: float, may_locate: bool) -> tuple[_Entry | None, bool]:
        """(entry or None if not attempted yet, whether a locate ran)."""
        key = (req['xid'], req['quote'])
        e = self._entries.get(req['id'])
        if e is not None and e.key == key:
            if e.segs is not None and self._verified(e, now):
                return e, False
            if e.segs is None and now - e.since < RETRY_AFTER:
                return e, False
        if not may_locate:
            return None, False
        segs = locate(req.get('pid'), req['xid'], req.get('anchor') or {}, req['quote'], LOCATE_BUDGET)
        e = _Entry(key, [_Seg(s) for s in segs] if segs else None, since=now, verified_at=now)
        self._entries[req['id']] = e
        return e, True

    def update(self, reqs: list[dict], focus: set[str]) -> dict:
        """reqs: [{id, xid, pid, anchor, quote}]. Measures the annotations from the window the user is working in,
        plus those in `focus`. Returns {'context': xid, 'items': {id: {state, rects}}, 'windows': {xid: {...}}}
        with state ok | offscreen (scrolled away) | missing (text not found) | hidden (window not shown)."""
        active = windows.active_window()
        if active is not None and active.pid != self.own_pid:
            self.context_xid = active.xid
        now = time.monotonic()
        wanted = {r['id'] for r in reqs}
        self._entries = {k: v for k, v in self._entries.items() if k in wanted}
        items: dict[str, dict] = {}
        wins: dict[int, dict] = {}
        located = False
        for req in sorted(reqs, key=lambda r: r['id'] not in focus):       # focused ones get located first
            xid = req['xid']
            if req['id'] not in focus and xid != self.context_xid:
                continue
            if xid not in wins:
                shown = windows.is_shown(xid)
                wins[xid] = {'shown': shown, 'rect': windows.client_rect(xid) if shown else None,
                             'occluders': windows.occluders(xid) if shown else []}
            if not wins[xid]['shown']:
                items[req['id']] = {'state': 'hidden', 'rects': []}
                continue
            e, ran = self._entry(req, now, may_locate=not located)
            located = located or ran
            if e is None:
                continue
            if e.segs is None:
                items[req['id']] = {'state': 'missing', 'rects': []}
                continue
            try:
                for s in e.segs:
                    _refresh(s, xid)
            except Exception:
                self._entries.pop(req['id'], None)    # the node went away: locate again on a later tick
                continue
            rects = [r for s in e.segs for r in s.rects()]
            items[req['id']] = {'state': 'ok' if rects else 'offscreen', 'rects': rects}
        return {'context': self.context_xid, 'items': items, 'windows': wins}

    def reveal(self, req: dict) -> bool:
        """Scroll the annotated text into view inside its window (locating it afresh)."""
        self._entries.pop(req['id'], None)
        e, _ = self._entry(req, time.monotonic(), may_locate=True)
        if e is None or not e.segs:
            return False
        return scroll_into_view(e.segs[0].seg)
