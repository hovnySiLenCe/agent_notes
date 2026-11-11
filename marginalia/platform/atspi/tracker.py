"""Keep the on-screen rectangles of annotated text up to date while the user scrolls. Worker thread only.

Each tick costs two character-extent queries per located text segment: when they haven't moved, the cached
rectangles are reused; when both ends moved by the same offset (scrolling), the rectangles are shifted and only
the clipping is recomputed; anything else (reflow, resize) re-measures. The text is re-verified every few
seconds and located again when it changed.

Chromium-based apps (VS Code …) refresh the positions they report only about every 500 ms. While content
scrolls, its motion is therefore also measured from the window's pixels (x11/motion.py): every rectangle remembers
which pixel offset of its window its AT-SPI position corresponds to (`snap`), and is drawn shifted by the motion
seen since. A stale AT-SPI position that later catches up by dy moves `snap` by dy, so the two never double-count.

Finding a quote that isn't where it was captured means walking the window's whole accessibility tree (VS Code's
chat drops messages scrolled far away, so this happens a lot). That walk never blocks tracking: it runs in small
slices after the measuring, pauses while the user scrolls, is shared by all quotes searched in that window, and
quotes that stay missing are searched for less and less often (again soon after each scroll, which may have
brought them back).
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field

from ..x11 import motion, windows
from .geometry import EMPTY, Rect, box_scale, intersect, scaled, scroll_pane, text_rects, visible_area, vte_rects
from .locate import Segment, collect, fast_locate, frames_for, locate, resolve, scroll_into_view, single_node
from .tree import OBJ, Atspi, T

log = logging.getLogger(__name__)

RETRY_AFTER = 3.0        # s before searching again for a quote that wasn't found; doubles with every miss …
RETRY_MAX = 60.0         # … up to this
VERIFY_EVERY = 2.0       # s between checks that the located text is still the same
SEARCH_SLICE = 0.015     # s per tick for finding quotes (fast-path checks + tree walking), little while scrolling
MOVING_SLICE = 0.003     # (enough to re-check a path, not to walk)
FRAME_TTL = 10.0         # s a window's frame lookup is reused (a cold lookup can take ~50 ms: never while scrolling)
RESYNC_S = 0.7           # s without pixel motion after which AT-SPI positions are taken as exact again (they
                         # refresh about every 0.5 s)
STRIP_W = 32             # px wide strips of the scroll pane watched for motion: where the text's lines start, …
STRIPS = (0.5, 0.8)      # … and at these fractions of the pane's width


@dataclass
class _Seg:
    seg: Segment
    probe: tuple | None = None
    raw: list[Rect] = field(default_factory=list)     # unclipped character-line rectangles
    clip: Rect | None = None                          # visible area of the containers (None = unknown)
    snap: int = 0                                     # the window's pixel-motion offset `raw` corresponds to
    pane: Rect | None = None                          # the scroll pane it moves in (doesn't move itself)
    box_scale: float | None = None                    # container boxes -> character coordinates (geometry.box_scale)

    def rects(self, offset: int = 0, pane: Rect | None = None) -> list[Rect]:
        """Visible rectangles, moved by the pixel motion seen since `raw` was measured (`offset`: the window's
        current motion offset; `pane`: the window's scroll pane, if this text's own isn't known). Moved text is
        clipped by the pane only: the containers inside it (paragraphs …) moved along."""
        pane = self.pane or pane
        dy = 0 if self.seg.terminal or pane is None else offset - self.snap
        raw = [(x, y + dy, w, h) for x, y, w, h in self.raw] if dy else self.raw
        clip = pane if dy else self.clip
        if clip is None:
            return raw
        if clip == EMPTY:
            return []
        return [r for r in (intersect(r, clip) for r in raw) if r]


@dataclass
class _Motion:
    """Pixel-motion tracking of one window's scroll pane."""
    pane: Rect | None = None         # screen rect of the scroll pane (from the clips of visible quotes)
    strip: tuple | None = None       # window-relative rect grabbed
    prev: object = None              # its last row signatures
    offset: int = 0                  # content motion seen so far (px, cumulative)
    guess: int = 0                   # last frame's motion
    moved_at: float = 0.0
    strip_x: int = 0                 # screen x where the watched strip starts
    moved_now: bool = False          # the pixels moved this tick
    motion_ticks: float = 0.0        # (decaying) count of ticks the pixels moved …
    live_ticks: float = 0.0          # … and of those where AT-SPI positions moved too
    atspi_moved: bool = False        # some AT-SPI position moved this tick

    @property
    def live(self) -> bool:
        """This app's AT-SPI positions follow scrolling at once (Firefox): use them as they are."""
        return self.motion_ticks >= 3 and self.live_ticks >= 0.6 * self.motion_ticks


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


def _refresh(s: _Seg, xid: int, offset: int = 0, origin: tuple = (0, 0)) -> bool:
    """Re-measure if the probe moved; True if it did. offset: the window's pixel-motion offset now; origin: the
    window's position."""
    p = _probe(s, xid)
    if p is None:
        return False
    if not s.seg.terminal:
        p = p + tuple(origin)
    if p == s.probe:
        return False
    old, s.probe = s.probe, p
    if s.seg.terminal:
        s.raw, s.clip = vte_rects(s.seg.node, xid, s.seg.start, s.seg.end), None
        return True
    if old is not None and p[1] - old[1] == p[3] - old[3] and p[2] - old[2] == p[4] - old[4]:
        dx, dy = p[1] - old[1], p[2] - old[2]          # scrolled or window moved: same shape, new place
        s.raw = [(x + dx, y + dy, w, h) for x, y, w, h in s.raw]
        scrolled = dy - (p[6] - old[6])                # (the part that is scrolling, not the window moving)
        pending = offset - s.snap                      # motion the pixels saw that AT-SPI hadn't shown yet
        if scrolled and pending and (scrolled > 0) == (pending > 0) and abs(scrolled) <= abs(pending):
            s.snap += scrolled                         # AT-SPI catching up
        elif scrolled:
            s.snap = offset                            # motion the pixels didn't see: AT-SPI is the truth
    else:
        s.raw = text_rects(s.seg.node, s.seg.start, s.seg.end)
        s.snap = offset
    if s.box_scale is None:
        ends = _ends(s.seg)
        s.box_scale = box_scale(s.seg.node, ends[0]) if ends else 1.0
    s.clip = scaled(visible_area(s.seg.node), s.box_scale)
    s.pane = scaled(scroll_pane(s.seg.node), s.box_scale)
    return True


class Tracker:
    def __init__(self, own_pid: int):
        self.own_pid = own_pid
        self.context_xid: int | None = None       # last active window that isn't one of ours
        self._entries: dict[str, _Entry] = {}
        self._walks: dict[int, _Walk] = {}         # xid -> walk in progress
        self._frames: dict[int, tuple] = {}        # xid -> (frame, looked up at)
        self._budget_end = 0.0                     # this tick's time for finding quotes ends here
        self._was_moving = False
        self._motion: dict[int, _Motion] = {}      # xid -> pixel-motion tracking of its scroll pane
        self._compositing: tuple[bool, float] = (False, -1e9)

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
        self._panes: dict[int, tuple] = {}            # xid -> (scroll pane, text column) seen this tick
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
                if shown and wins[xid]['rect']:
                    self._follow_pixels(xid, wins[xid]['rect'], now)
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
            self._measure(req, e, items, self._motion.get(xid), wins[xid]['rect'])
        searching = bool(wanted) and self._search(wanted, self._budget_end if not moving else 0)
        for lst in wanted.values():                   # settled just now: show them right away
            for req, e in lst:
                if e.segs is not None:
                    self._measure(req, e, items, self._motion.get(req['xid']), wins[req['xid']]['rect'])
                elif e.misses:
                    items[req['id']] = {'state': 'missing', 'rects': []}
        for mot in self._motion.values():             # does AT-SPI move along with the pixels in this app?
            if mot.moved_now:
                mot.motion_ticks = mot.motion_ticks * 0.9 + 1
                mot.live_ticks = mot.live_ticks * 0.9 + mot.atspi_moved
            mot.moved_now = mot.atspi_moved = False
        for xid, (pane, x) in self._panes.items():
            mot = self._motion.get(xid)
            if mot is not None and (mot.pane is None or now - mot.moved_at > RESYNC_S):   # (not mid-scroll)
                mot.pane, mot.strip_x = pane, x
        self._motion = {x: m for x, m in self._motion.items() if x in wins}
        return {'context': self.context_xid, 'items': items, 'windows': wins,
                'searching': searching or deferred or (bool(wanted) and moving)}

    def _measure(self, req: dict, e: _Entry, items: dict, mot: _Motion | None, win_rect) -> None:
        offset, pane = (mot.offset, mot.pane) if mot else (0, None)
        try:
            changed = [_refresh(s, req['xid'], offset, win_rect[:2] if win_rect else (0, 0)) for s in e.segs]
        except Exception:                             # the node went away: find it again on a later tick
            e.segs, e.misses, e.retry_at = None, 0, 0.0
            return
        if mot is not None:
            mot.atspi_moved = mot.atspi_moved or any(changed)
            if mot.live:
                for s in e.segs:
                    s.snap = offset                   # no compensation: AT-SPI is current
        rects = []
        for s in e.segs:
            r = s.rects(offset, pane)
            rects += r
            if r and s.pane not in (None, EMPTY) and not s.seg.terminal:
                # watch the pane this visible text scrolls in, at the column where its lines start
                self._panes.setdefault(req['xid'], (s.pane, min(x for x, _, _, _ in r)))
        items[req['id']] = {'state': 'ok' if rects else 'offscreen', 'rects': rects}
        if offset and log.isEnabledFor(logging.DEBUG):
            log.debug('%s: offset %s snap %s raw %s clip %s pane %s -> %s', req['id'], offset,
                      [s.snap for s in e.segs], [s.raw[:1] for s in e.segs], [s.clip for s in e.segs],
                      [s.pane for s in e.segs], rects[:1])

    def _pixels_usable(self) -> bool:
        """Only with a compositor: then a window's image is its own buffer, without our overlay painted over it."""
        on, at = self._compositing
        if time.monotonic() - at > 10:
            on = bool(windows.compositing()) and not os.environ.get('MARGINALIA_NO_PIXEL_MOTION')   # (tests compare)
            self._compositing = (on, time.monotonic())
        return on

    def _follow_pixels(self, xid: int, win_rect, now: float) -> None:
        """Advance the window's pixel-motion offset by the content motion since the last tick."""
        if not self._pixels_usable():
            return
        mot = self._motion.setdefault(xid, _Motion())
        if mot.pane is None:
            return
        wx, wy, ww, wh = win_rect
        px, py, pw, ph = mot.pane
        xs = sorted({min(max(x, px), px + pw - STRIP_W) - wx for x in
                     [mot.strip_x] + [px + int(pw * f) for f in STRIPS]})
        strip = (tuple(xs), py - wy, STRIP_W, ph)
        if xs[0] < 0 or strip[1] < 0 or xs[-1] + STRIP_W > ww or strip[1] + ph > wh:
            mot.pane = mot.strip = mot.prev = None
            return
        cur = motion.grab_strip(xid, *strip)
        dy = motion.shift(mot.prev, cur, mot.guess) if cur is not None and mot.prev is not None \
            and strip == mot.strip else None
        mot.strip, mot.prev = strip, cur
        if dy or (dy is None and log.isEnabledFor(logging.DEBUG)):
            log.debug('pixels %s: shift %s offset %s pane %s strip %s', xid, dy, mot.offset + (dy or 0), mot.pane, strip)
        if dy:
            mot.offset += dy
            mot.guess = dy
            mot.moved_at = now
            mot.moved_now = True
        else:
            mot.guess = 0
            if now - mot.moved_at > RESYNC_S:         # quiet: AT-SPI has caught up, its positions are exact
                for e in self._entries.values():
                    if e.key[0] == xid:
                        for sg in e.segs or []:
                            sg.snap = mot.offset

    def reveal(self, req: dict) -> bool:
        """Scroll the annotated text into view inside its window (locating it afresh)."""
        self._entries.pop(req['id'], None)
        segs = locate(req.get('pid'), req['xid'], req.get('anchor') or {}, req['quote'])
        if not segs:
            return False
        return scroll_into_view(segs[0])
