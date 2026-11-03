import base64
import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

spec = importlib.util.spec_from_file_location('ish_update', Path(__file__).parents[1] / 'raspberry-pi/ish-update.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class HostKeyDiscovery(unittest.TestCase):
    def test_only_matching_pinned_key_is_selected(self):
        key = b'test-only-ssh-key'
        encoded = base64.b64encode(key).decode()
        fingerprint = 'SHA256:' + base64.b64encode(hashlib.sha256(key).digest()).decode().rstrip('=')
        result = SimpleNamespace(stdout='10.0.0.8 ssh-ed25519 ' + encoded + '\n')
        with patch.object(helper.socket, 'create_connection', return_value=MagicMock()), patch.object(helper.subprocess, 'run', return_value=result) as run:
            self.assertIsNone(helper.locate('10.0.0.8'))
            with patch.object(helper, 'FINGERPRINT', fingerprint):
                address, line = helper.locate('10.0.0.8')
            self.assertEqual(address, '10.0.0.8')
            self.assertEqual(line, 'pi-station-sean ssh-ed25519 ' + encoded + '\n')
            self.assertTrue(all(call.args[0][0] == 'ssh-keyscan' for call in run.call_args_list))

    def test_malformed_key_is_not_accepted(self):
        with patch.object(helper.socket, 'create_connection', return_value=MagicMock()), patch.object(helper.subprocess, 'run', return_value=SimpleNamespace(stdout='host ssh-ed25519 !!bad!!')):
            self.assertIsNone(helper.locate('10.0.0.9'))
