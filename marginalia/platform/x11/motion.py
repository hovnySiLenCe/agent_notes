"""Follow scrolling by looking at the pixels: how far did a window's content move between two frames?

Chromium-based apps (VS Code, Chrome, Electron) refresh the on-screen positions they report over AT-SPI only
about every 500 ms, so highlights driven by those positions alone jump twice a second while scrolling. The
window's own pixels are always current: a few narrow vertical strips of the scroll pane are grabbed from the
target window (with a compositor that is the window's own buffer, so our overlay is not in it), reduced to a few
numbers per pixel row, and matched against the previous frame to find the vertical shift. Where several shifts
match about equally well (repetitive content: a list whose lines all start alike), the one that continues the
current motion wins, and no motion at all is better than a wrong jump: the AT-SPI positions catch up anyway.
"""
from __future__ import annotations

import numpy as np
from Xlib import X, error

from . import display as xd

BINS = 6              # columns per row signature (some horizontal structure, robust to anti-aliasing)
MAX_SHIFT = 640       # px per frame searched (physical px; a fast fling at ~60 fps stays well within this)
MIN_OVERLAP = 0.35    # the two frames must share at least this fraction of the strip
FLAT = 2.0            # a strip whose rows barely differ (empty area) can't tell motion
TIE = 1.3             # matches within this factor of the best one (squared differences) count as equally good


def grab_strip(xid: int, xs, y: int, w: int, h: int) -> np.ndarray | None:
    """Row signatures (h, BINS per strip) of window-relative strips at columns `xs`, or None (window gone /
    off its bounds)."""
    if w < BINS or h < 16:
        return None
    parts = []
    try:
        win = xd.get().create_resource_object('window', xid)
        for x in xs:
            img = win.get_image(x, y, w, h, X.ZPixmap, 0xFFFFFFFF)
            a = np.frombuffer(img.data, np.uint8)
            if a.size != w * h * 4:
                return None
            g = a.reshape(h, w, 4)[:, :w - w % BINS, 1].astype(np.float32)     # green is enough to see text
            parts.append(g.reshape(h, BINS, -1).mean(axis=2))
    except (error.XError, error.BadMatch, ValueError):
        return None
    return np.concatenate(parts, axis=1)


def _ssd_all(a: np.ndarray, b: np.ndarray, lim: int) -> tuple[np.ndarray, np.ndarray]:
    """(shifts -lim..lim, mean squared difference between a[y + s] and b[y] over their overlap) for every shift
    at once: sum a² + sum b² over the overlap (cumulative sums) minus twice the cross term (FFT)."""
    n = len(a)
    size = 1 << (2 * n - 1).bit_length()
    cross = np.fft.irfft(np.fft.rfft(a, size, axis=0) * np.conj(np.fft.rfft(b, size, axis=0)), size, axis=0).sum(axis=1)
    ca = np.concatenate([[0.0], np.cumsum((a * a).sum(axis=1))])
    cb = np.concatenate([[0.0], np.cumsum((b * b).sum(axis=1))])
    shifts = np.arange(-lim, lim + 1)
    lo_a, hi_a = np.maximum(0, shifts), np.minimum(n, n + shifts)       # a's rows in the overlap
    lo_b, hi_b = np.maximum(0, -shifts), np.minimum(n, n - shifts)      # b's rows
    overlap = hi_a - lo_a
    ssd = ca[hi_a] - ca[lo_a] + cb[hi_b] - cb[lo_b] - 2 * cross[shifts % size]
    ssd = np.maximum(ssd, 0) / np.maximum(overlap * a.shape[1], 1)
    ssd[overlap < n * MIN_OVERLAP] = np.inf
    return shifts, ssd


def shift(prev: np.ndarray, cur: np.ndarray, guess: int = 0) -> int | None:
    """Vertical content motion from `prev` to `cur` in px (negative: content moved up, i.e. scrolled down),
    or None when the strip doesn't show enough structure to tell. `guess` (the last frame's motion) breaks
    ties between equally good matches (repetitive content)."""
    if prev.shape != cur.shape or float(cur.std(axis=0).mean()) < FLAT:
        return None
    if np.array_equal(prev, cur):          # the usual case while nothing scrolls: no need to search
        return 0
    lim = min(MAX_SHIFT, int(len(cur) * (1 - MIN_OVERLAP)))
    shifts, ssd = _ssd_all(prev, cur, lim)
    floor = float(ssd.min())
    if not np.isfinite(floor):
        return None
    pad = np.concatenate([[np.inf], ssd, [np.inf]])
    minima = (ssd <= pad[:-2]) & (ssd <= pad[2:])                # local minima only: not a best match's neighbours
    tied = shifts[minima & (ssd <= floor * TIE + 1.0)]
    s = int(min(tied, key=lambda c: abs(c + guess)))           # equally good: continue the current motion
    return -s           # prev[y + s] == cur[y]: the content moved by -s
