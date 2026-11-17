import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from marginalia.__main__ import _preload_xcb_cursor  # noqa: E402

_preload_xcb_cursor()

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from marginalia import config as cfgmod  # noqa: E402
from marginalia.core.models import Annotation  # noqa: E402
from marginalia.core.store import Store  # noqa: E402
from marginalia.ui import settings as smod  # noqa: E402


class HotkeySpecTest(unittest.TestCase):
    def test_specs(self):
        A, S, C = Qt.AltModifier, Qt.ShiftModifier, Qt.ControlModifier
        self.assertEqual(smod.hotkey_spec(S | A, Qt.Key_Y), 'Shift+Alt+Y')
        self.assertEqual(smod.hotkey_spec(A, Qt.Key_Return), 'Alt+Return')
        self.assertEqual(smod.hotkey_spec(C | A, Qt.Key_Comma), 'Ctrl+Alt+comma')
        self.assertEqual(smod.hotkey_spec(S | A, Qt.Key_Exclam, '!'), 'Shift+Alt+1')   # Shift+1 arrives as '!'
        self.assertEqual(smod.hotkey_spec(S | A, Qt.Key_Plus, '+'), 'Shift+Alt+equal')  # never a bare '+'
        self.assertEqual(smod.hotkey_spec(Qt.NoModifier, Qt.Key_F8), 'F8')
        self.assertEqual(smod.hotkey_spec(Qt.NoModifier, Qt.Key_Y), '')      # would steal Y from every app
        self.assertEqual(smod.hotkey_spec(S, Qt.Key_Y), '')
        self.assertEqual(smod._norm('alt+shift+y'), smod._norm('Shift+Alt+Y'))

    def test_specs_parse_as_x11_hotkeys(self):
        from marginalia.platform.x11.hotkeys import parse
        for spec in ('Shift+Alt+Y', 'Ctrl+Alt+comma', 'Shift+Alt+1', 'Alt+Return', 'Super+Prior', 'F8'):
            parse(spec)


class SettingsWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {'MARGINALIA_CONFIG_DIR': self.tmp.name,
                                                'MARGINALIA_DATA_DIR': self.tmp.name})
        self.env.start()
        self.path = cfgmod.config_path()
        user = {'panel': {'opacity': 0.8}, 'hotkeys': {'menu': 'Shift+Alt+S'}, 'mine': 1}
        self.path.write_text(json.dumps(user), encoding='utf-8')
        self.reloads = []
        self.suspended = []
        self.ctl = SimpleNamespace(cfg=cfgmod.Config.load()[0], store=Store(Path(self.tmp.name) / 'n.db'),
                                   reload_config=lambda: self.reloads.append(1),
                                   suspend_hotkeys=self.suspended.append)
        self.win = smod.SettingsWindow(self.ctl)

    def tearDown(self):
        self.win._dirty = False
        self.win.close()
        self.win.deleteLater()
        self.env.stop()
        self.tmp.cleanup()

    def saved(self) -> dict:
        return json.loads(self.path.read_text(encoding='utf-8'))

    def test_edit_type_and_save_keeps_the_rest_of_the_file(self):
        page = self.win.types_page
        self.assertFalse(self.win.save_btn.isEnabled())             # nothing changed yet
        page.list.setCurrentRow(1)
        page.name.setText('不同意')
        page.name.textEdited.emit('不同意')
        page.template.setPlainText('【不同意】{{quote}}')
        self.assertTrue(self.win.save_btn.isEnabled())
        self.assertTrue(self.win.save())
        data = self.saved()
        self.assertEqual(data['types'][1]['name'], '不同意')
        self.assertEqual(data['types'][1]['template'], '【不同意】{{quote}}')
        self.assertEqual((data['panel'], data['mine']), ({'opacity': 0.8}, 1))   # untouched sections stay
        self.assertTrue(self.path.with_name('config.json.bak').exists())
        self.assertEqual(self.reloads, [1])
        cfg, err = cfgmod.Config.load()
        self.assertIsNone(err)
        self.assertEqual(cfg.types[1].name, '不同意')

    def test_add_move_delete(self):
        page = self.win.types_page
        n = len(page.types)
        page.add_type()
        self.assertEqual(len(page.types), n + 1)
        self.assertEqual(page.current()['id'], 'custom1')
        page.move(-1)
        self.assertEqual(page.types[n - 1]['id'], 'custom1')
        page.add_type()
        self.assertEqual(page.current()['id'], 'custom2')
        page.delete_type(confirm=False)
        self.assertEqual([t['id'] for t in page.types].count('custom2'), 0)
        page.list.setCurrentRow(0)
        page.delete_type(confirm=False)
        self.assertTrue(self.win.save())
        ids = [t['id'] for t in self.saved()['types']]
        self.assertEqual(ids[0], 'disagree')
        self.assertEqual(ids[-2], 'custom1')

    def test_conflicting_hotkeys_block_saving(self):
        page = self.win.types_page
        page.list.setCurrentRow(5)                      # 纠错: no hotkey by default
        page._set('hotkey', 'Alt+Shift+y')              # same as YES's Shift+Alt+Y
        self.assertFalse(self.win.save_btn.isEnabled())
        self.assertIn('Shift+Alt+Y 同时分配给了', self.win.error.text())
        self.assertIn('「YES」', self.win.error.text())
        self.assertFalse(self.win.save())
        page._set('hotkey', 'Ctrl+Alt+J')
        self.assertTrue(self.win.save_btn.isEnabled())
        self.win.hotkeys_page.edits['fill_plain'].set_spec('Ctrl+Alt+J')
        self.win.hotkeys_page.changed.emit()
        self.assertFalse(self.win.save_btn.isEnabled())

    def test_empty_or_duplicate_names_block_saving(self):
        page = self.win.types_page
        page._set('name', '')
        self.assertIn('没有名称', self.win.error.text())
        page._set('name', 'NO')                         # type 0 renamed to type 1's name
        self.assertIn('重名', self.win.error.text())

    def test_hotkey_edit_records_and_suspends_grabs(self):
        from PySide6.QtTest import QTest
        self.win.show()
        page = self.win.types_page
        page.list.setCurrentRow(5)
        edit = page.hotkey
        edit.setFocus()
        self.win.activateWindow()
        QApplication.processEvents()
        if not edit.hasFocus():                         # offscreen windows do not always get focus
            from PySide6.QtCore import QEvent
            from PySide6.QtGui import QFocusEvent
            QApplication.sendEvent(edit, QFocusEvent(QEvent.FocusIn, Qt.MouseFocusReason))
        self.assertEqual(self.suspended[-1], True)
        QTest.keyClick(edit, Qt.Key_K, Qt.ControlModifier | Qt.AltModifier)
        QApplication.processEvents()
        self.assertEqual(page.current()['hotkey'], 'Ctrl+Alt+K')
        self.assertEqual(self.suspended[-1], False)                    # grabs are back after recording

    def test_prompt_page_and_preview(self):
        p = self.win.prompt_page
        p.header.setPlainText('看下面的批注：')
        p.newline.setChecked(True)
        self.assertIn('看下面的批注：', p.preview.text())
        self.assertIn('1. 【YES】', p.preview.text())
        self.assertTrue(self.win.save())
        self.assertEqual(self.saved()['prompt']['header'], '看下面的批注：')
        self.assertTrue(self.saved()['prompt']['trailing_newline'])

    def test_type_preview_follows_input_mode(self):
        page = self.win.types_page
        page.list.setCurrentRow(4)                      # REMARK: comment required
        self.assertNotIn('不写说明', page.preview.text())
        self.assertIn(smod.SAMPLE_COMMENT, page.preview.text())
        page.input.setCurrentIndex(0)                   # none
        self.assertEqual(page.current()['input'], 'none')
        self.assertNotIn('写了说明', page.preview.text())

    def test_reset_types_page(self):
        page = self.win.types_page
        page.delete_type(confirm=False)
        self.win.reset(page)
        self.assertEqual([t['id'] for t in page.types], [t['id'] for t in cfgmod.DEFAULT_TYPES])
        self.assertTrue(self.win._dirty)

    def test_deleting_a_used_type_mentions_its_annotations(self):
        self.ctl.store.add(Annotation('agree', 'x'))
        with mock.patch.object(QMessageBox, 'question', return_value=QMessageBox.No) as q:
            self.win.types_page.delete_type()
        self.assertIn('1 条批注', q.call_args[0][2])
        self.assertEqual(self.win.types_page.types[0]['id'], 'agree')   # answered No: kept

    def test_save_sections_refuses_invalid_types(self):
        with self.assertRaises(ValueError):
            cfgmod.save_sections({'types': [{'id': 'a', 'name': 'A'}, {'id': 'a', 'name': 'B'}]})
        self.assertEqual(self.saved()['mine'], 1)                      # file untouched


if __name__ == '__main__':
    unittest.main()
