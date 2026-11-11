import sys
import unittest

from marginalia import qtfix


class EmitLeakTest(unittest.TestCase):
    def test_installed_pyside_keeps_true_alive(self):
        """Fails on PySide6 6.12.0 (run ./scripts/setup.sh); the app still survives it through qtfix.apply()."""
        self.assertFalse(qtfix.emit_drops_true())

    def test_apply_is_harmless_on_a_good_version(self):
        before = sys.getrefcount(True)
        qtfix.apply()
        self.assertLess(abs(sys.getrefcount(True) - before), 1 << 20)


if __name__ == '__main__':
    unittest.main()
