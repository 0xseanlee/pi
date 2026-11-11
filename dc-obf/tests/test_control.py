import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from dc_obf import cli, control
from dc_obf.updater import lock


class ControlTests(unittest.TestCase):
    def test_close_when_offline_is_harmless_and_needs_no_token(self):
        with tempfile.TemporaryDirectory(dir='/tmp') as root, patch('dc_obf.control.Path.home', return_value=Path(root)), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(control.close_bot(), 0)
            self.assertFalse(control.control_path().exists())
            self.assertFalse((Path(root)/'.config/dc/obf.json').exists())

    def test_no_socket_does_not_stop_update_or_other_process(self):
        with tempfile.TemporaryDirectory(dir='/tmp') as root, patch('dc_obf.control.Path.home', return_value=Path(root)):
            with lock('obf.run.lock'):
                with self.assertRaisesRegex(RuntimeError, '舊版 Bot'):
                    control.close_bot()

    def test_phone_dash_dispatches_close_without_loading_token(self):
        with patch('dc_obf.cli.sys.argv', ['dc', 'obf', '—close']), patch(
            'dc_obf.control.close_bot', return_value=0) as close_bot, patch('dc_obf.cli.load_config') as load_config:
            self.assertEqual(cli.main(), 0)
            close_bot.assert_called_once_with()
            load_config.assert_not_called()

    def test_close_cancels_real_worker_and_preserves_source_and_status(self):
        # A separate bot process and a real worker, with Discord I/O replaced.
        # Stop travels over the same Unix socket used on the Pi; no Discord token.
        script = r'''
import asyncio
import os
from pathlib import Path
import types
from unittest.mock import AsyncMock, patch
from dc_obf.bot import OBFClient, run

root = Path.home()
closed = None
worker_code = "import os,time; from pathlib import Path; Path(" + repr(str(root/'worker.pid')) + ").write_text(str(os.getpid())); time.sleep(30)"
configuration = {'application_id': 2, 'owner_id': 1, 'token': 'test-placeholder',
                 'engine_argv': ['{python}', '-c', worker_code, '{input}', '{output}']}

async def fake_start(self, token):
    self.closed_event = asyncio.Event()
    interaction = types.SimpleNamespace(id=123, user=types.SimpleNamespace(id=1),
        response=types.SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
        edit_original_response=AsyncMock())
    attachment = types.SimpleNamespace(filename='source.lua', size=10, read=AsyncMock(return_value=b'return 123'))
    task = asyncio.create_task(self.obfuscate(interaction, attachment))
    await self.closed_event.wait()

async def fake_close(self):
    if hasattr(self, 'closed_event'):
        self.closed_event.set()

with patch.object(OBFClient, 'start', fake_start), patch.object(OBFClient, 'close', fake_close):
    raise SystemExit(run(configuration))
'''
        with tempfile.TemporaryDirectory(dir='/tmp') as root, patch('dc_obf.control.Path.home', return_value=Path(root)):
            env = os.environ.copy()
            env['HOME'] = root
            child = subprocess.Popen([sys.executable, '-c', script], env=env,
                                     cwd=Path(__file__).resolve().parents[1], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                marker = Path(root)/'worker.pid'
                deadline = time.monotonic() + 5
                while not marker.exists() and child.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.02)
                if not marker.exists():
                    child.terminate()
                    stdout, stderr = child.communicate(timeout=5)
                    self.fail('worker did not start: ' + stdout + stderr)
                pid = int(marker.read_text())
                with contextlib.redirect_stdout(io.StringIO()) as stdout:
                    self.assertEqual(control.close_bot(timeout=5), 0)
                child.communicate(timeout=5)
                self.assertEqual(child.returncode, 130)
                self.assertFalse(control.control_path().exists())
                self.assertFalse(control.running())
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)
                job = next((Path(root)/'.local/share/dc-obf/jobs').iterdir())
                self.assertEqual((job/'input.lua').read_bytes(), b'return 123')
                self.assertEqual(json.loads((job/'job.json').read_text())['status'], 'cancelled')
                self.assertIn('已停止', stdout.getvalue())
            finally:
                if child.poll() is None:
                    child.terminate()
                    child.communicate(timeout=5)
