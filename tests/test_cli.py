import tempfile
import unittest
from pathlib import Path

from agent_notes.__main__ import FIREFOX_PREF, firefox_profiles, setup_firefox


class SetupFirefoxTest(unittest.TestCase):
    def test_writes_pref_once_and_keeps_other_prefs(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            snap = home / 'snap/firefox/common/.mozilla/firefox/abc.default'
            deb = home / '.mozilla/firefox/xyz.default-release'
            for p in (snap, deb):
                p.mkdir(parents=True)
                (p / 'prefs.js').write_text('')
            (snap / 'user.js').write_text('user_pref("a.b", 1);\nuser_pref("accessibility.force_disabled", 1);\n')
            (home / '.mozilla/firefox/no-prefs').mkdir()
            self.assertEqual(set(firefox_profiles(home)), {snap, deb})
            self.assertEqual(setup_firefox(home), 0)
            self.assertEqual(setup_firefox(home), 0)           # idempotent
            self.assertEqual((snap / 'user.js').read_text().splitlines(), ['user_pref("a.b", 1);', FIREFOX_PREF])
            self.assertEqual((deb / 'user.js').read_text().splitlines(), [FIREFOX_PREF])

    def test_no_profiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(setup_firefox(Path(tmp)), 1)


if __name__ == '__main__':
    unittest.main()
