"""Keep the on-screen rectangles of annotated text up to date while the user scrolls. Worker thread only.

Each tick costs two character-extent queries per located text segment: when they haven't moved, the cached
rectangles are reused; when both ends moved by the same offset (scrolling), the rectangles are shifted and only
the clipping is recomputed; anything else (reflow, resize) re-measures. The text is re-verified every few
seconds and located again when it changed.

Finding a quote that isn't where it was captured means walking the window's whole accessibility tree (VS Code's
chat drops messages scrolled far away, so this happens a lot). That walk never blocks tracking: it runs in small
slices after the measuring, pauses while the user scrolls, is shared by all quotes searched in that window, and
quotes that stay missing are searched for less and less often (again soon after each scroll, which may have
brought them back).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..x11 import windows
from .geometry import EMPTY, Rect, intersect, text_rects, visible_area, vte_rects
from .locate import Segment, collect, fast_locate, frames_for, locate, resolve, scroll_into_view, single_node
from .tree import OBJ, Atspi, T

RETRY_AFTER = 3.0        # s before searching again for a quote that wasn't found; doubles with every miss …
RETRY_MAX = 60.0         # … up to this
VERIFY_EVERY = 2.0       # s between checks that the located text is still the same
SEARCH_SLICE = 0.015     # s per tick for finding quotes (fast-path checks + tree walking), little while scrolling
MOVING_SLICE = 0.003     # (enough to re-check a path, not to walk)
FRAME_TTL = 10.0         # s a window's frame lookup is reused (a cold lookup can take ~50 ms: never while scrolling)


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
    segs: list[_Seg] | None = None   # None: not found (yet)
    verified_at: float = 0.0
    searching: bool = False          # waiting for its window's tree walk
    partial: list[Segment] | None = None   # fast path's first segment of a multi-node capture
    misses: int = 0                  # searches in a row that didn't find it
    retry_at: float = 0.0


@dataclass
class _Walk:
    """A resumable walk over one window's tree, collecting its text nodes."""
    nodes: list
    steps: object                    # the collect() generator
    done: bool = False

    def run(self, until: float) -> None:
        try:
            while time.monotonic() < until:
                next(self.steps)
        except StopIteration:
            self.done = True
        except Exception:            # the tree changed under us badly enough: use what we have
            self.done = True


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
        self._walks: dict[int, _Walk] = {}         # xid -> walk in progress
        self._frames: dict[int, tuple] = {}        # xid -> (frame, looked up at)
        self._budget_end = 0.0                     # this tick's time for finding quotes ends here
        self._was_moving = False

    def _verified(self, e: _Entry, now: float) -> bool:
        if now - e.verified_at < VERIFY_EVERY:
            return True
        try:
            ok = all(T.get_text(s.seg.node, s.seg.start, s.seg.end) == s.seg.text for s in e.segs or [])
        except Exception:
            ok = False
        e.verified_at = now
        return ok

    def _frame(self, req: dict):
        xid, now = req['xid'], time.monotonic()
        hit = self._frames.get(xid)
        if hit is None or now - hit[1] > FRAME_TTL:
            frames = frames_for(req.get('pid'), xid)
            hit = self._frames[xid] = (frames[0] if frames else None, now)
        return hit[0]

    def _entry(self, req: dict, now: float) -> _Entry:
        """The entry for `req`, trying the (cheap) fast path when it needs finding; otherwise it is left
        `searching` for its window's walk."""
        key = (req['xid'], req['quote'])
        e = self._entries.get(req['id'])
        if e is None or e.key != key:
            e = self._entries[req['id']] = _Entry(key)
        elif e.segs is not None:
            if self._verified(e, now):
                return e
            e.segs, e.misses = None, 0             # the text changed: find it again now
        elif e.searching or now < e.retry_at:
            return e
        if time.monotonic() > self._budget_end:    # this tick's time is used up: next tick
            return e
        if self._was_moving and req['xid'] not in self._frames:
            return e
        anchor, quote = req.get('anchor') or {}, req['quote']
        frame = self._frame(req)
        fast = fast_locate(frame, anchor, quote) if frame is not None else None
        if fast is not None and single_node(anchor):
            e.segs, e.misses, e.verified_at, e.partial = [_Seg(s) for s in fast], 0, now, None
        else:
            e.searching, e.partial = True, fast
        return e

    def _search(self, wanted: dict[int, list], until: float) -> bool:
        """Advance the walks of windows with quotes to find; when a walk completes, settle its quotes.
        Returns True while a search is still in progress."""
        self._walks = {x: w for x, w in self._walks.items() if x in wanted}
        for xid, lst in wanted.items():
            if time.monotonic() >= until:
                break
            w = self._walks.get(xid)
            if w is None:
                frame = self._frame(lst[0][0])
                nodes: list = []
                w = self._walks[xid] = _Walk(nodes, collect(frame, nodes) if frame is not None else iter(()))
            w.run(until)
            if not w.done:
                continue
            del self._walks[xid]
            now = time.monotonic()
            for req, e in lst:
                try:
                    segs = resolve(w.nodes, req.get('anchor') or {}, req['quote'], e.partial)
                except Exception:
                    segs = None
                e.searching, e.partial = False, None
                if segs:
                    e.segs, e.misses, e.verified_at = [_Seg(s) for s in segs], 0, now
                else:
                    e.misses += 1
                    e.retry_at = now + min(RETRY_MAX, RETRY_AFTER * 2 ** (e.misses - 1))
                    self._frames.pop(xid, None)    # (in case the window was rebuilt: look its frame up afresh)
        return bool(self._walks)

    def update(self, reqs: list[dict], focus: set[str], moving: bool = False) -> dict:
        """reqs: [{id, xid, pid, anchor, quote}]. Measures the annotations from the window the user is working in,
        plus those in `focus`. moving: the user is scrolling (no time for searching).
        Returns {'context': xid, 'items': {id: {state, rects}}, 'windows': {xid: {...}}, 'searching': bool}
        with state ok | offscreen (scrolled away) | missing (text not found) | hidden (window not shown)."""
        active = windows.active_window()
        if active is not None and active.pid != self.own_pid:
            self.context_xid = active.xid
        now = time.monotonic()
        self._budget_end = now + (MOVING_SLICE if moving else SEARCH_SLICE)
        self._frames = {x: f for x, f in self._frames.items() if now - f[1] <= FRAME_TTL}
        wanted_ids = {r['id'] for r in reqs}
        self._entries = {k: v for k, v in self._entries.items() if k in wanted_ids}
        if self._was_moving and not moving:        # scrolling stopped: missing quotes may be back in the tree
            for e in self._entries.values():
                e.retry_at = min(e.retry_at, now)
        self._was_moving = moving
        items: dict[str, dict] = {}
        wins: dict[int, dict] = {}
        wanted: dict[int, list] = {}
        deferred = False                              # due for finding, but this tick's time ran out
        for req in sorted(reqs, key=lambda r: r['id'] not in focus):       # focused ones get searched first
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
            try:
                e = self._entry(req, now)
            except Exception:
                continue
            if e.segs is None:
                if e.searching:
                    wanted.setdefault(xid, []).append((req, e))
                elif now >= e.retry_at:
                    deferred = True
                if e.misses:
                    items[req['id']] = {'state': 'missing', 'rects': []}
                continue
            self._measure(req, e, items)
        searching = bool(wanted) and self._search(wanted, self._budget_end if not moving else 0)
        for lst in wanted.values():                   # settled just now: show them right away
            for req, e in lst:
                if e.segs is not None:
                    self._measure(req, e, items)
                elif e.misses:
                    items[req['id']] = {'state': 'missing', 'rects': []}
        return {'context': self.context_xid, 'items': items, 'windows': wins,
                'searching': searching or deferred or (bool(wanted) and moving)}

    @staticmethod
    def _measure(req: dict, e: _Entry, items: dict) -> None:
        try:
            for s in e.segs:
                _refresh(s, req['xid'])
        except Exception:                             # the node went away: find it again on a later tick
            e.segs, e.misses, e.retry_at = None, 0, 0.0
            return
        rects = [r for s in e.segs for r in s.rects()]
        items[req['id']] = {'state': 'ok' if rects else 'offscreen', 'rects': rects}

    def reveal(self, req: dict) -> bool:
        """Scroll the annotated text into view inside its window (locating it afresh)."""
        self._entries.pop(req['id'], None)
        segs = locate(req.get('pid'), req['xid'], req.get('anchor') or {}, req['quote'])
        if not segs:
            return False
        return scroll_into_view(segs[0])
