import os
import subprocess
import unittest

from marginalia.platform.x11 import windows


class RelatedPidsTest(unittest.TestCase):
    def test_a_child_leads_back_to_its_parent(self):
        """A selection set by a helper the window's app started (Claude Code -> xclip) counts as the app's."""
        child = subprocess.Popen(['sleep', '5'])
        try:
            self.assertIn(os.getpid(), windows._related_pids(child.pid))
            self.assertNotIn(os.getpid(), windows._related_pids(1))
        finally:
            child.kill()
            child.wait()


if __name__ == '__main__':
    unittest.main()
