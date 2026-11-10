from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dc_obf.updater import activate, lock


class UpdateTests(unittest.TestCase):
    def test_incomplete_release_never_replaces_current(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            old, new = root/'old', root/'new'
            old.mkdir(); new.mkdir()
            (root/'current').symlink_to(old)
            with self.assertRaises(RuntimeError):
                activate(root, new)
            self.assertEqual((root/'current').resolve(), old)

    def test_atomic_activation_keeps_previous(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            old, new = root/'old', root/'new'
            old.mkdir(); new.mkdir(); (new/'.ready').touch()
            (root/'current').symlink_to(old)
            activate(root, new)
            self.assertEqual((root/'current').resolve(), new)
            self.assertEqual((root/'previous').resolve(), old)

    def test_concurrent_run_or_update_is_rejected(self):
        with tempfile.TemporaryDirectory() as root, patch('dc_obf.updater.Path.home', return_value=Path(root)):
            with lock('obf.run.lock'):
                with self.assertRaises(RuntimeError):
                    with lock('obf.run.lock'):
                        self.fail('unexpected concurrent lock')
