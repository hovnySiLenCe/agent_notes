import time
import unittest
from types import SimpleNamespace
from unittest import mock

from marginalia.platform.atspi import tracker as tr
from marginalia.platform.atspi.locate import Segment

WIN = 7
FRAME = object()


def req(id_, quote):
    return {'id': id_, 'xid': WIN, 'pid': 1, 'anchor': {'method': 'atspi', 'path': [0]}, 'quote': quote}


class TrackerSearchTest(unittest.TestCase):
    """The tree walk behind a search runs in slices, is shared by a window's quotes and never runs while scrolling."""

    def setUp(self):
        self.walks = 0
        self.tree = ['alpha'] + [f'x{i}' for i in range(6)] + ['beta']      # text nodes of the fake window

        def collect(frame, out):
            self.walks += 1
            for t in list(self.tree):
                time.sleep(0.01)                     # ~0.1 ms per node in reality; slow enough to need slices here
                out.append((t, (len(out),), t))
                yield

        def resolve(nodes, anchor, quote, fast):
            hit = next((n for n, _, t in nodes if t == quote), None)
            return [Segment(hit, 0, len(quote), quote)] if hit else None

        def refresh(s, xid):
            s.raw = [(10, 10, 50, 10)]
        win = SimpleNamespace(active_window=lambda: SimpleNamespace(pid=2, xid=WIN), is_shown=lambda x: True,
                              client_rect=lambda x: (0, 0, 800, 600), occluders=lambda x: [])
        for name, value in (('windows', win), ('collect', collect), ('resolve', resolve), ('_refresh', refresh),
                            ('frames_for', lambda pid, xid: [FRAME]), ('fast_locate', lambda *a: None),
                            ('SEARCH_SLICE', 0.025)):
            p = mock.patch.object(tr, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.t = tr.Tracker(own_pid=1)

    def run_until_settled(self, reqs, limit=20):
        for _ in range(limit):
            res = self.t.update(reqs, set())
            if not res['searching']:
                return res
        self.fail('search never finished')

    def test_one_sliced_walk_serves_all_quotes(self):
        reqs = [req('a', 'alpha'), req('b', 'beta'), req('c', 'gone')]
        first = self.t.update(reqs, set())
        self.assertTrue(first['searching'])           # a slice is shorter than the walk
        res = self.run_until_settled(reqs)
        self.assertEqual(self.walks, 1)
        self.assertEqual({k: v['state'] for k, v in res['items'].items()}, {'a': 'ok', 'b': 'ok', 'c': 'missing'})

    def test_no_searching_while_scrolling(self):
        reqs = [req('a', 'alpha')]
        for _ in range(3):
            t0 = time.monotonic()
            res = self.t.update(reqs, set(), moving=True)
            self.assertLess(time.monotonic() - t0, 0.01)
            self.assertTrue(res['searching'])
        self.assertEqual(self.walks, 0)
        self.assertEqual(self.run_until_settled(reqs)['items']['a']['state'], 'ok')

    def test_missing_quote_backs_off_until_a_scroll(self):
        reqs = [req('c', 'gone')]
        self.run_until_settled(reqs)
        self.assertEqual(self.walks, 1)
        for _ in range(3):                             # within the retry delay: no new walks
            self.assertEqual(self.t.update(reqs, set())['items']['c']['state'], 'missing')
        self.assertEqual(self.walks, 1)
        self.tree.append('gone')                       # scrolling brought it back into the tree
        self.t.update(reqs, set(), moving=True)
        res = self.run_until_settled(reqs)            # scroll ended: searched again at once
        self.assertEqual(self.walks, 2)
        self.assertEqual(res['items']['c']['state'], 'ok')
        e = self.t._entries['c']
        self.assertEqual(e.misses, 0)

    def test_retry_delay_doubles(self):
        reqs = [req('c', 'gone')]
        self.run_until_settled(reqs)
        e = self.t._entries['c']
        d1 = e.retry_at - time.monotonic()
        e.retry_at = 0
        self.run_until_settled(reqs)
        d2 = e.retry_at - time.monotonic()
        self.assertAlmostEqual(d2, 2 * d1, delta=0.3)


if __name__ == '__main__':
    unittest.main()
