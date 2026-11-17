"""What keeps Alt+Return / Shift+Alt+Return fast: urgent worker calls, the remembered input box, and a paste that
only waits for the hotkey's release where it has to."""
import os
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from marginalia.__main__ import _preload_xcb_cursor  # noqa: E402

_preload_xcb_cursor()

from PySide6.QtCore import QCoreApplication  # noqa: E402

from marginalia.platform.base import WindowInfo  # noqa: E402
from marginalia.worker import Worker  # noqa: E402


class WorkerPriorityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_urgent_calls_overtake_queued_background_ones(self):
        w = Worker()
        gate = threading.Event()
        order = []
        w.submit(lambda: gate.wait(2))                  # the worker is busy with something
        for i in range(3):
            w.submit(lambda i=i: order.append(f'track{i}'))
        w.submit(lambda: order.append('inject'), urgent=True)
        w.submit(lambda: order.append('activate'), urgent=True)
        gate.set()
        end = time.monotonic() + 2
        while len(order) < 5 and time.monotonic() < end:
            time.sleep(0.01)
        self.assertEqual(order, ['inject', 'activate', 'track0', 'track1', 'track2'])
        w.shutdown()

    def test_results_come_back_on_the_qt_thread(self):
        w = Worker()
        got = []
        w.submit(lambda x: x * 2, 21, cb=got.append, urgent=True)
        end = time.monotonic() + 2
        while not got and time.monotonic() < end:
            QCoreApplication.processEvents()
            time.sleep(0.01)
        self.assertEqual(got, [42])
        w.shutdown()


class InputCacheTest(unittest.TestCase):
    def setUp(self):
        from marginalia.platform.atspi import inputs
        self.inputs = inputs
        inputs._last.clear()
        self.searches = 0
        node = object()

        def search(frame, anchor_path, budget):
            self.searches += 1
            return node, (0, 3, 1)
        patches = [mock.patch.object(inputs, 'frame_for', lambda pid, title: 'frame'),
                   mock.patch.object(inputs, '_search', search),
                   mock.patch.object(inputs, '_usable', lambda n: True),
                   mock.patch('marginalia.platform.atspi.locate.node_at', lambda root, path: (node, None, ()))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_cache_survives_title_changes(self):
        self.inputs.find_input(5, 'a.py - proj - Visual Studio Code', None, xid=77)
        self.inputs.find_input(5, 'b.py - proj - Visual Studio Code', None, xid=77)    # another file opened
        self.assertEqual(self.searches, 1)

    def test_hint_from_the_main_process_skips_the_walk(self):
        """A recycled helper has no cache of its own: the path the app remembered is used."""
        node, path = self.inputs.find_input(5, 't', None, xid=77, hint=[0, 3, 1])
        self.assertEqual((self.searches, path), (0, (0, 3, 1)))


class InjectOrderTest(unittest.TestCase):
    def setUp(self):
        from marginalia.platform import x11
        self.x11 = x11
        self.events = []
        self.active = 9
        self.grabbed = False
        ev = self.events

        def focus_input(pid, title, anchor_path, xid=0, hint=None):
            ev.append('focus_input')
            return {'name': 'Message input', 'path': [1, 2], 'grabbed': self.grabbed}
        patches = [
            mock.patch.object(x11.windows, 'active_xid', lambda: self.active),
            mock.patch.object(x11.windows, 'activate', lambda xid: (ev.append('activate'), setattr(self, 'active', xid))),
            mock.patch.object(x11.windows, 'wait_active', lambda xid, t: True),
            mock.patch.object(x11.keys, 'wait_keys_released', lambda: ev.append('released')),
            mock.patch.object(x11.keys, 'send', lambda combo: ev.append(combo)),
            mock.patch('marginalia.platform.atspi.inputs.focus_input', focus_input),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.plat = x11.X11Platform.__new__(x11.X11Platform)
        self.target = WindowInfo(xid=9, pid=5, wm_class='Code', wm_instance='code', title='t')

    def test_input_is_found_before_waiting_for_the_keys(self):
        t = time.monotonic()
        res = self.plat.inject(self.target, False, None, False, False, [1, 2])
        self.assertLess(time.monotonic() - t, 0.1)                      # focus already there: no settle sleep
        self.assertEqual(self.events, ['focus_input', 'released', 'ctrl+End', 'ctrl+v'])   # already active
        self.assertEqual(res['input_path'], [1, 2])
        self.assertIn('pasted', res['ms'])

    def test_moved_focus_gets_time_to_settle(self):
        self.grabbed = True
        self.active = 3
        t = time.monotonic()
        self.plat.inject(self.target, False, None, False)
        self.assertGreaterEqual(time.monotonic() - t, 0.14)
        self.assertEqual(self.events[:2], ['activate', 'focus_input'])

    def test_at_cursor_skips_the_lookup(self):
        self.plat.inject(self.target, False, None, False, True)
        self.assertEqual(self.events, ['released', 'ctrl+v'])


if __name__ == '__main__':
    unittest.main()
