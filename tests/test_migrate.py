import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from marginalia import config


class MigrateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.cfg, self.data = root / 'cfg', root / 'data'
        env = {k: v for k, v in os.environ.items() if not k.startswith('MARGINALIA_')}
        env.update(XDG_CONFIG_HOME=str(self.cfg), XDG_DATA_HOME=str(self.data))
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def test_old_dirs_are_moved_once(self):
        (self.cfg / 'agent-notes').mkdir(parents=True)
        (self.cfg / 'agent-notes' / 'config.json').write_text('{}')
        (self.data / 'agent-notes').mkdir(parents=True)
        (self.data / 'agent-notes' / 'notes.db').write_text('x')
        self.assertEqual(len(config.migrate_old_dirs()), 2)
        self.assertTrue((config.config_dir() / 'config.json').exists())
        self.assertTrue((config.data_dir() / 'notes.db').exists())
        self.assertFalse((self.cfg / 'agent-notes').exists())
        self.assertEqual(config.migrate_old_dirs(), [])

    def test_existing_new_dir_is_left_alone(self):
        (self.cfg / 'agent-notes').mkdir(parents=True)
        (self.cfg / 'marginalia').mkdir(parents=True)
        self.assertEqual(config.migrate_old_dirs(), [])
        self.assertTrue((self.cfg / 'agent-notes').exists())


if __name__ == '__main__':
    unittest.main()
