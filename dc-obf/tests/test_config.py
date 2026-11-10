import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dc_obf import config, cli

TOKEN = 'unit-test-discord-token-not-a-real-secret'
IDENTITY = {'application_id': 123456789012345678, 'owner_id': 234567890123456789}


class ConfigurationTests(unittest.TestCase):
    def test_setup_saves_private_config_and_does_not_start_bot(self):
        with tempfile.TemporaryDirectory() as root, patch('dc_obf.config.Path.home', return_value=Path(root)), patch(
            'dc_obf.config.validate_token', return_value=IDENTITY
        ), patch('dc_obf.cli.sys.stdin.isatty', return_value=True), patch(
            'dc_obf.cli.getpass.getpass', return_value=TOKEN
        ), patch('dc_obf.cli.os.umask'), contextlib.redirect_stdout(io.StringIO()) as stdout:
            cli.setup()
            path = config.config_path()
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(config.load_config()['owner_id'], IDENTITY['owner_id'])
            self.assertNotIn(TOKEN, stdout.getvalue())
            self.assertFalse(path.with_suffix('.token').exists())
            self.assertIn('dc obf', stdout.getvalue())

    def test_failed_verification_keeps_candidate_without_enabling_it(self):
        with tempfile.TemporaryDirectory() as root, patch('dc_obf.config.Path.home', return_value=Path(root)), patch(
            'dc_obf.config.validate_token', side_effect=config.ConfigError('network unavailable')
        ):
            with self.assertRaises(config.ConfigError):
                config.save_token(TOKEN)
            self.assertEqual(config.saved_token(), TOKEN)
            self.assertFalse(config.config_path().exists())

    def test_insecure_config_is_rejected(self):
        with tempfile.TemporaryDirectory() as root, patch('dc_obf.config.Path.home', return_value=Path(root)):
            path = config.config_path()
            config.private_write(path, json.dumps({**IDENTITY, 'token': TOKEN}))
            path.chmod(0o644)
            with self.assertRaises(config.ConfigError):
                config.load_config()

    def test_invite_contains_no_token_or_admin_permission(self):
        url = config.invite_url(IDENTITY['application_id'])
        self.assertNotIn(TOKEN, url)
        self.assertIn('permissions=35840', url)

    def test_setup_requires_user_terminal(self):
        with patch('dc_obf.cli.sys.stdin.isatty', return_value=False), patch('dc_obf.cli.getpass.getpass') as prompt:
            with self.assertRaises(config.ConfigError):
                cli.setup()
            prompt.assert_not_called()
