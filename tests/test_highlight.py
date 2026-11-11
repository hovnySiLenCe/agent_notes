import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')   # no window ever appears on the desktop

from marginalia.__main__ import _preload_xcb_cursor  # noqa: E402

_preload_xcb_cursor()

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from marginalia import config as cfgmod  # noqa: E402
from marginalia.core.models import SENT, Annotation  # noqa: E402
from marginalia.core.store import Store  # noqa: E402
from marginalia.highlight import Highlighter  # noqa: E402

XID, OTHER = 0x400001, 0x500001


class FakeWorker:
    def __init__(self):
        self.calls = []

    def submit(self, fn, *args, cb=None):
        self.calls.append((fn, args))
        if cb:
            cb(fn(*args))


class HighlighterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.track_result = {}
        self.platform = SimpleNamespace(track=lambda reqs, focus, moving=False: self.track_result, window_exists=lambda x: True,
                                        activate=lambda x: None, reveal=lambda req: True)
        self.ctl = SimpleNamespace(cfg=cfgmod.Config(json.loads(json.dumps(cfgmod.DEFAULTS))), state={},
                                   store=Store(Path(self.tmp.name) / 'n.db'), worker=FakeWorker(),
                                   platform=self.platform, save_state=lambda: None, _busy=False, panel=None,
                                   toast=SimpleNamespace(show_message=lambda *a, **k: self.toasts.append(a),
                                                         isVisible=lambda: False))
        self.toasts = []
        self.hl = Highlighter(self.ctl)
        st = self.ctl.store
        anchor = {'method': 'atspi', 'path': [0], 'start': 0, 'end': 3}
        self.a = st.add(Annotation('expand', 'foo', anchor=anchor, source={'xid': XID, 'pid': 1}))
        self.b = st.add(Annotation('ask', 'bar', comment='?', anchor=anchor, source={'xid': OTHER, 'pid': 2}))

    def tearDown(self):
        self.hl.overlay.hide()
        self.tmp.cleanup()

    def result(self, items, context=XID, occluders=()):
        return {'context': context, 'items': items,
                'windows': {XID: {'shown': True, 'rect': (0, 0, 1000, 800), 'occluders': list(occluders)},
                            OTHER: {'shown': True, 'rect': (0, 0, 1000, 800), 'occluders': []}}}

    def test_requests_only_for_anchored_annotations(self):
        self.ctl.store.add(Annotation('keep', 'x', anchor={'method': 'primary'}, source={'xid': XID}))
        reqs = [r for r in (self.hl.request(a) for a in self.hl.candidates()) if r]
        self.assertEqual({r['id'] for r in reqs}, {self.a.id, self.b.id})

    def test_marks_follow_the_working_window_and_are_clipped(self):
        moved = self.hl.apply(self.result({
            self.a.id: {'state': 'ok', 'rects': [(100, 100, 200, 20), (100, 130, 950, 20)]},
            self.b.id: {'state': 'ok', 'rects': [(10, 10, 50, 20)]}},
            occluders=[(150, 90, 30, 50)]))
        self.assertTrue(moved)
        marks = self.hl.overlay.marks
        self.assertEqual(len(marks), 1)                       # only the window the user works in
        region_rects = set((r.x(), r.y(), r.width(), r.height()) for r in marks[0].rects)
        self.assertNotIn((100, 100, 200, 20), region_rects)    # cut by the window above it
        covered = sum(r.width() * r.height() for r in marks[0].rects)
        # line 1 loses the occluded 30x20; line 2 is cut at the window edge (x=1000) and loses 30x10
        self.assertEqual(covered, 200 * 20 - 30 * 20 + 900 * 20 - 30 * 10)
        self.assertEqual(marks[0].color, self.ctl.cfg.type_map['expand'].color)
        self.assertTrue(self.hl.overlay.isVisible())
        self.assertEqual(self.hl.states[self.a.id], 'ok')
        self.assertFalse(self.hl.apply(self.result({
            self.a.id: {'state': 'ok', 'rects': [(100, 100, 200, 20), (100, 130, 950, 20)]},
            self.b.id: {'state': 'ok', 'rects': [(10, 10, 50, 20)]}}, occluders=[(150, 90, 30, 50)])))

    def test_hover_shows_annotation_from_another_window_emphasized(self):
        self.hl.set_hover(self.b.id)
        self.hl.apply(self.result({self.b.id: {'state': 'ok', 'rects': [(10, 10, 50, 20)]}}))
        self.assertEqual([m.focus for m in self.hl.overlay.marks], [True])

    def test_hover_mode_and_sent_items(self):
        self.ctl.store.set_status([self.a.id], SENT)
        self.assertEqual({a.id for a in self.hl.candidates()}, {self.b.id})
        self.ctl.cfg.data['highlight']['show'] = 'all'
        self.assertEqual({a.id for a in self.hl.candidates()}, {self.a.id, self.b.id})
        self.ctl.cfg.data['highlight']['show'] = 'hover'
        self.assertEqual(self.hl.candidates(), [])
        self.hl.set_hover(self.a.id)
        self.assertEqual([a.id for a in self.hl.candidates()], [self.a.id])

    def test_disabled_hides_overlay_and_stops_tracking(self):
        self.hl.apply(self.result({self.a.id: {'state': 'ok', 'rects': [(100, 100, 200, 20)]}}))
        self.assertTrue(self.hl.overlay.isVisible())
        self.hl.set_enabled(False)
        self.hl.tick()
        self.assertFalse(self.hl.overlay.isVisible())
        self.assertEqual(self.ctl.worker.calls, [])

    def test_tick_goes_through_worker_and_paints(self):
        self.track_result = self.result({self.a.id: {'state': 'ok', 'rects': [(100, 100, 200, 20)]}})
        self.hl.tick()
        self.assertEqual(len(self.ctl.worker.calls), 1)
        self.assertEqual(self.hl.overlay.geometry().adjusted(3, 3, -3, -3), QRect(100, 100, 200, 20))

    def test_wheel_switches_to_fast_polling(self):
        from marginalia import highlight
        self.track_result = self.result({self.a.id: {'state': 'ok', 'rects': [(100, 100, 200, 20)]}})
        self.hl.tick()                                   # first paint counts as movement
        self.hl.tick()                                   # unchanged picture
        self.hl._moving_until = 0.0
        self.hl.tick()
        self.assertEqual(self.hl._timer.interval(), highlight.SLOW_MS)
        self.hl.scrolled()
        self.hl.tick()
        self.assertLessEqual(self.hl._timer.interval(), highlight.FAST_MS)
        self.assertTrue(self.ctl.worker.calls[-1][1][2])     # the tracker is told the user is scrolling

    def test_jump_flashes_or_reports_missing(self):
        self.hl.jump(self.a)
        self.assertIn(self.a.id, self.hl.focus_ids())
        self.platform.reveal = lambda req: False
        self.hl.jump(self.b)
        self.assertNotIn(self.b.id, self.hl.focus_ids())
        self.assertTrue(self.toasts)


if __name__ == '__main__':
    unittest.main()
