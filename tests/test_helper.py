import os
import signal
import tempfile
import time
import unittest

from agent_notes import helper as helpermod
from agent_notes.helper import Helper, HelperError
from agent_notes.platform.base import WindowInfo

TERM = WindowInfo(xid=1, pid=1, wm_class='gnome-terminal-server', wm_instance='', title='t')
EDIT = WindowInfo(xid=2, pid=2, wm_class='Code', wm_instance='code', title='e')


class HelperTest(unittest.TestCase):
    """Runs a real helper process (only pure platform methods: no X / AT-SPI needed)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = os.environ.get('AGENT_NOTES_DATA_DIR')
        os.environ['AGENT_NOTES_DATA_DIR'] = self.tmp.name      # the helper logs there, not into the real log
        self.h = Helper(os.getpid())

    def tearDown(self):
        self.h.close()
        if self.env is None:
            os.environ.pop('AGENT_NOTES_DATA_DIR', None)
        else:
            os.environ['AGENT_NOTES_DATA_DIR'] = self.env
        self.tmp.cleanup()

    def test_round_trip(self):
        self.assertTrue(self.h.call('is_terminal', TERM))
        self.assertFalse(self.h.call('is_terminal', EDIT))

    def test_errors_come_back_as_exceptions(self):
        with self.assertRaises(HelperError):
            self.h.call('is_terminal')                 # missing argument

    def test_killed_helper_is_replaced(self):
        self.h.call('is_terminal', TERM)
        os.kill(self.h._proc.pid, signal.SIGKILL)       # what a segfault in libatspi looks like from here
        try:
            self.assertTrue(self.h.call('is_terminal', TERM))   # detected before sending: new helper
        except HelperError:
            self.assertTrue(self.h.call('is_terminal', TERM))   # or the call fails and the next one works

    def test_hung_helper_is_killed_and_replaced(self):
        self.h.call('is_terminal', TERM)
        old = helpermod.CALL_TIMEOUT
        helpermod.CALL_TIMEOUT = 0.5
        try:
            os.kill(self.h._proc.pid, signal.SIGSTOP)
            t = time.monotonic()
            with self.assertRaises(HelperError):
                self.h.call('is_terminal', TERM)
            self.assertLess(time.monotonic() - t, 5)
        finally:
            helpermod.CALL_TIMEOUT = old
        self.assertTrue(self.h.call('is_terminal', TERM))
        self.assertEqual(self.h.restarts, 1)


if __name__ == '__main__':
    unittest.main()
