import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')   # no window ever appears on the desktop

from marginalia.__main__ import _preload_xcb_cursor  # noqa: E402

_preload_xcb_cursor()

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QApplication, QToolButton  # noqa: E402

from marginalia.core.models import AnnoType  # noqa: E402
from marginalia.ui.bubble import SelectionBubble  # noqa: E402


class BubbleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_buttons_and_choice(self):
        b = SelectionBubble()
        types = [AnnoType('expand', '展开', hotkey='Shift+Alt+E'), AnnoType('ask', '追问')]
        b.set_types(types, {'expand': 'Shift+Alt+E', '': 'Shift+Alt+S'})
        buttons = b.findChildren(QToolButton)
        self.assertEqual([x.text() for x in buttons], ['展开', '追问', '⋯'])
        self.assertIn('Shift+Alt+E', buttons[0].toolTip())
        got = []
        b.chosen.connect(got.append)
        b.show_at(QPoint(100, 100))
        self.assertTrue(b.isVisible())
        buttons[1].click()
        buttons[2].click()
        self.assertEqual(got, ['ask', ''])
        self.assertFalse(b.isVisible())                        # hides once a choice is made


if __name__ == '__main__':
    unittest.main()
