import unittest
from unittest import mock

import numpy as np

from marginalia.platform.atspi import tracker as tr
from marginalia.platform.atspi.locate import Segment
from marginalia.platform.x11 import motion


def page(h=5000, seed=1):
    """Row signatures of a text-like page: lines of 'glyphs' separated by blank leading."""
    rng = np.random.default_rng(seed)
    rows = np.full((h, motion.BINS), 250.0, np.float32)
    y = 0
    while y < h:
        line = int(rng.integers(28, 40))
        ink = rng.uniform(80, 200, motion.BINS) * (rng.random(motion.BINS) > 0.2)
        rows[y + 6:min(h, y + line - 8)] -= ink
        y += line
    return rows


class ShiftTest(unittest.TestCase):
    def test_finds_scroll_both_ways(self):
        p = page()
        view = slice(1000, 3500)
        for d in (0, 3, -3, 17, -40, 120, -240, 600):
            prev, cur = p[view], p[1000 + d:3500 + d]          # scrolled down by d: content moves up by d
            self.assertEqual(motion.shift(prev, cur), -d, d)

    def test_repetitive_content_never_jumps_wrongly(self):
        line = page(100, seed=3)
        p = np.concatenate([line] * 40)                        # identical lines, 100 px apart
        prev, cur = p[1000:3000], p[1100:3100]                # scrolled by exactly one line: looks like no motion
        self.assertIn(motion.shift(prev, cur), (0, -100))
        prev, cur = p[1000:3000], p[1040:3040]                # 40 px: unambiguous
        self.assertEqual(motion.shift(prev, cur), -40)

    def test_flat_area_cannot_tell(self):
        flat = np.full((2000, motion.BINS), 240.0, np.float32)
        self.assertIsNone(motion.shift(flat, flat))


class SnapTest(unittest.TestCase):
    """AT-SPI positions that lag behind the pixels must neither double-count nor jump back."""

    def setUp(self):
        self.y = 500                                          # where AT-SPI says the text is
        probe = lambda s, xid: ('g', 100, self.y, 300, self.y)
        rects = lambda node, a, b: [(100, self.y, 200, 20)]
        for name, value in (('_probe', probe), ('text_rects', rects), ('visible_area', lambda n: (0, 0, 1000, 1000)),
                            ('scroll_pane', lambda n: (0, 0, 1000, 1000))):
            p = mock.patch.object(tr, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.s = tr._Seg(Segment(object(), 0, 10, 'x' * 10))
        tr._refresh(self.s, 1, 0, (0, 0))

    def ys(self, offset):
        return [r[1] for r in self.s.rects(offset)]

    def test_pixels_lead_atspi_catches_up(self):
        self.assertEqual(self.ys(0), [500])
        self.assertEqual(self.ys(-240), [260])                 # scrolled: the pixels saw it, AT-SPI not yet
        tr._refresh(self.s, 1, -240, (0, 0))                    # (stale probe: nothing changes)
        self.assertEqual(self.ys(-240), [260])
        self.y = 380                                          # AT-SPI catches up halfway …
        tr._refresh(self.s, 1, -480, (0, 0))                    # … while the pixels went on to -480
        self.assertEqual(self.ys(-480), [20])
        self.y = 20                                           # … and fully
        tr._refresh(self.s, 1, -480, (0, 0))
        self.assertEqual(self.ys(-480), [20])

    def test_text_scrolled_out_of_the_pane_is_clipped(self):
        self.assertEqual(self.ys(-600), [])                    # moved above the pane's top
        self.assertEqual(self.ys(480), [980])                 # partly below its bottom: clipped to it
        self.assertEqual(self.s.rects(480)[0][3], 20)

    def test_motion_the_pixels_missed_follows_atspi(self):
        self.y = 300                                          # scrolled, but no pixel motion seen (no compositor …)
        tr._refresh(self.s, 1, 0, (0, 0))
        self.assertEqual(self.ys(0), [300])
        self.y = 100                                          # pixels saw 50 of a 200 px scroll
        tr._refresh(self.s, 1, -50, (0, 0))
        self.assertEqual(self.ys(-50), [100])

    def test_window_move_is_not_scrolling(self):
        self.y = 600                                          # the window moved down by 100, content didn't scroll
        tr._refresh(self.s, 1, 0, (0, 100))
        self.assertEqual(self.ys(0), [600])


class LiveTest(unittest.TestCase):
    def test_live_when_atspi_moves_with_the_pixels(self):
        m = tr._Motion()
        for atspi in (True, True, False, True, True):
            m.motion_ticks = m.motion_ticks * 0.9 + 1
            m.live_ticks = m.live_ticks * 0.9 + atspi
        self.assertTrue(m.live)                               # Firefox-like
        m = tr._Motion()
        for k in range(30):                                   # Chromium-like: AT-SPI moves every ~0.5 s
            m.motion_ticks = m.motion_ticks * 0.9 + 1
            m.live_ticks = m.live_ticks * 0.9 + (k % 30 == 29)
        self.assertFalse(m.live)


if __name__ == '__main__':
    unittest.main()
