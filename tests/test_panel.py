import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')   # no window ever appears on the desktop

from marginalia.__main__ import _preload_xcb_cursor  # noqa: E402

_preload_xcb_cursor()

from PySide6.QtWidgets import QApplication  # noqa: E402

from marginalia import config as cfgmod  # noqa: E402
from marginalia.core.store import Store  # noqa: E402
from marginalia.ui.panel import FloatingPanel  # noqa: E402


class PanelOpacityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        noop = lambda *a, **k: None  # noqa: E731
        self.ctl = SimpleNamespace(cfg=cfgmod.Config(json.loads(json.dumps(cfgmod.DEFAULTS))),
                                   state={'panel': {'x': 400, 'y': 300, 'w': 380, 'h': 560}},
                                   store=Store(Path(self.tmp.name) / 'n.db'), compose=lambda items: '',
                                   open_config=noop, reload_config=noop, quit=noop, fill=noop, save_state=noop)
        self.panel = FloatingPanel(self.ctl)

    def tearDown(self):
        self.panel.deleteLater()
        self.tmp.cleanup()

    def test_collapse_keeps_right_edge_and_restores(self):
        full = self.panel.geometry()
        self.panel.set_collapsed(True)
        bar = self.panel.geometry()
        self.assertLess(bar.height(), 80)
        self.assertLess(bar.width(), full.width())
        self.assertEqual(bar.right(), full.right())
        self.assertAlmostEqual(self.panel.target_opacity(), 0.5)      # collapsed bar: see-through
        self.panel.set_collapsed(False)
        self.assertEqual(self.panel.geometry(), full)
        self.assertAlmostEqual(self.panel.target_opacity(), 0.96)     # full panel: solid

    def test_broken_saved_size_is_repaired(self):
        self.ctl.state['panel'] = {'x': 400, 'y': 300, 'w': 300, 'h': 64}    # the list had no room left
        panel = FloatingPanel(self.ctl)
        self.assertGreaterEqual(panel.geometry().height(), 160)
        panel.deleteLater()

    def test_expanding_reapplies_the_size_the_wm_lost(self):
        full = self.panel.geometry()
        self.panel.set_collapsed(True)
        self.panel.set_collapsed(False)
        self.panel.resize(300, 64)                    # a late configure from the window manager
        self.panel._settle()
        self.assertEqual(self.panel.geometry(), full)
        self.panel._settle_until = 0
        self.panel._save_geometry()
        self.assertEqual((self.ctl.state['panel']['w'], self.ctl.state['panel']['h']), (full.width(), full.height()))

    def _pointer_at(self, x, y):
        from PySide6.QtCore import QPoint
        self.panel._pointer = lambda: QPoint(x, y)

    def test_pointer_proximity_expands_and_distance_collapses(self):
        self.panel.show()
        self._pointer_at(0, 0)                                   # far away
        self.panel._track_pointer()
        self.assertTrue(self.panel._collapsed)
        bar = self.panel.geometry()
        self._pointer_at(bar.left() - 30, bar.center().y())       # 30 px left of the bar (< 40)
        self.panel._track_pointer()
        self.assertFalse(self.panel._collapsed)
        self.panel._track_pointer()                              # same spot, now near the full panel: stays open
        self.assertFalse(self.panel._collapsed)
        self._pointer_at(bar.left() - 30, bar.top() - 60)        # 60 px above: beyond the margin
        self.panel._track_pointer()
        self.assertTrue(self.panel._collapsed)

    def test_pin_prevents_auto_collapse(self):
        self.panel.show()
        self._pointer_at(0, 0)
        self.panel.set_pinned(True)
        self.panel._track_pointer()
        self.assertFalse(self.panel._collapsed)
        self.panel.set_pinned(False)
        self.panel._track_pointer()
        self.assertTrue(self.panel._collapsed)
        self.panel.set_pinned(True)                              # pinning expands again
        self.assertFalse(self.panel._collapsed)

    def test_show_has_grace_period(self):
        self._pointer_at(0, 0)
        self.panel.show_panel()
        self.panel._track_pointer()
        self.assertFalse(self.panel._collapsed)                  # visible for a moment before tucking away

    def test_delete_card_and_clear_menu(self):
        from marginalia.core.models import SENT, Annotation
        st = self.ctl.store
        a = st.add(Annotation('expand', 'A', created_at=1.0))
        b = st.add(Annotation('ask', 'B', comment='q', created_at=2.0))
        c = st.add(Annotation('keep', 'C', created_at=3.0))
        st.set_status([a.id], SENT, checked=False)
        self.panel.refresh()
        cards = {x.ann.id: x for x in self.panel._list._cards}
        cards[c.id].del_btn.click()                              # per-card ✕
        self.assertEqual({x.id for x in st.all()}, {a.id, b.id})
        self.panel._fill_trash_menu()
        labels = [act.text() for act in self.panel._trash_menu.actions() if act.text()]
        self.assertEqual(labels, ['删除已勾选的 1 条', '清空已发送的 1 条', '清空已解决的 0 条', '清空全部 2 条…'])
        sent = [x for x in st.all() if x.status == SENT]
        self.panel.delete_items(sent)                            # 清空已发送 (history)
        self.assertEqual([x.id for x in st.all()], [b.id])

    def test_resolve_and_reopen(self):
        from marginalia.core.models import PENDING, RESOLVED, Annotation
        st = self.ctl.store
        a = st.add(Annotation('ask', 'A', created_at=1.0))
        self.panel.refresh()
        self.panel._list._cards[0].done_btn.click()             # ✓ on the card
        self.assertEqual((st.get(a.id).status, st.get(a.id).checked), (RESOLVED, False))
        self.panel.refresh()
        card = self.panel._list._cards[0]
        self.assertEqual(card.done_btn.text(), '↺')
        self.assertEqual(self.panel.fill_items(st.all()), [])   # resolved items are not filled
        card.done_btn.click()                                    # reopen
        self.assertEqual((st.get(a.id).status, st.get(a.id).checked), (PENDING, True))

    def test_reveal_does_not_expand_a_collapsed_bar(self):
        self.panel.show()
        self.panel.set_collapsed(True)
        self.panel.reveal()
        self.assertTrue(self.panel._collapsed)

    def test_newest_first_list_but_chronological_prompt(self):
        from marginalia.core.models import Annotation
        st = self.ctl.store
        a = st.add(Annotation('expand', 'first', created_at=1.0))
        b = st.add(Annotation('expand', 'second', created_at=2.0))
        self.panel.refresh()
        self.assertEqual([c.ann.id for c in self.panel._list._cards], [b.id, a.id])
        self.assertEqual([x.id for x in self.panel.prompt_items()], [a.id, b.id])

    def test_sent_annotations_can_be_rechecked_and_refilled(self):
        from marginalia.core.models import SENT, Annotation
        st = self.ctl.store
        a = st.add(Annotation('expand', 'A'))
        b = st.add(Annotation('ask', 'B', comment='q'))
        st.set_status([a.id, b.id], SENT, checked=False)
        self.panel.refresh()
        self.assertEqual(self.panel.fill_items(), [])
        cards = {c.ann.id: c for c in self.panel._list._cards}
        self.assertTrue(cards[a.id].check.isEnabled())
        cards[a.id].check.setChecked(True)            # user re-checks a sent card
        self.assertEqual([x.id for x in self.panel.fill_items()], [a.id])

    def test_config_values_are_clamped(self):
        self.ctl.cfg.panel['idle_opacity'] = 0
        self.ctl.cfg.panel['opacity'] = 3
        self.assertAlmostEqual(self.panel.target_opacity(), 1.0)
        self.panel.set_collapsed(True)
        self.assertAlmostEqual(self.panel.target_opacity(), 0.15)

    def test_button_labels_follow_hotkeys(self):
        from marginalia.ui.panel import short_hotkey
        self.assertEqual(short_hotkey('Shift+Alt+Return'), '⇧⌥↵')
        self.assertEqual(short_hotkey('Alt+Return'), '⌥↵')
        self.panel.refresh()
        self.assertTrue(self.panel._plain_btn.text().endswith('⌥↵'))
        self.assertTrue(self.panel._fill_btn.text().endswith('⇧⌥↵'))

    def test_hide_tooltip_follows_hotkey_config(self):
        self.panel.refresh()
        self.assertIn('Shift+Alt+D', self.panel._close_btn.toolTip())


if __name__ == '__main__':
    unittest.main()
