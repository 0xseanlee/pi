import contextlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from dc_obf import background, cli, control


class BackgroundTests(unittest.TestCase):
    def test_default_command_backgrounds_and_foreground_remains_explicit(self):
        with patch('dc_obf.cli.load_config', return_value={'token': 'test-placeholder'}), patch(
            'dc_obf.background.start_background', return_value=0) as start, patch(
            'dc_obf.bot.run', return_value=0) as run, patch('dc_obf.cli.os.umask'):
            with patch('dc_obf.cli.sys.argv', ['dc', 'obf']):
                self.assertEqual(cli.main(), 0)
                start.assert_called_once_with()
                run.assert_not_called()
            with patch('dc_obf.cli.sys.argv', ['dc', 'obf', '--foreground']):
                self.assertEqual(cli.main(), 0)
                run.assert_called_once_with({'token': 'test-placeholder'})

    def test_failed_background_start_is_reported_and_logs_are_private(self):
        with tempfile.TemporaryDirectory(dir='/tmp') as root, patch('dc_obf.background.Path.home', return_value=Path(root)):
            with self.assertRaisesRegex(RuntimeError, '啟動未完成'):
                background.start_background(command=[sys.executable, '-c', 'raise SystemExit(1)'])
            self.assertEqual(background.log_path().stat().st_mode & 0o777, 0o600)
            self.assertFalse(control.running())

    def test_detached_bot_survives_launcher_exit_and_hangup_without_duplicates(self):
        bot_script = r'''
import asyncio,json,os
from pathlib import Path
from unittest.mock import patch
from dc_obf.bot import OBFClient,run

async def start(self, token):
    self.closed_event = asyncio.Event()
    Path.home().joinpath('background.json').write_text(json.dumps({'pid': os.getpid(), 'sid': os.getsid(0)}))
    print('private background output', flush=True)
    await self.closed_event.wait()
async def close(self):
    if hasattr(self, 'closed_event'):
        self.closed_event.set()
with patch.object(OBFClient,'start',start), patch.object(OBFClient,'close',close), patch.object(OBFClient,'is_ready',lambda self: True):
    raise SystemExit(run({'application_id':2,'owner_id':1,'token':'test-placeholder','engine_argv':[]}))
'''
        launcher_script = r'''
import json,os,sys,time
from pathlib import Path
from dc_obf.background import start_background
print('launcher-session=' + str(os.getsid(0)), flush=True)
result = start_background(command=[sys.executable,'-c',sys.argv[1]])
if len(sys.argv) > 2 and result == 0:
    sys.stdout.flush()
    Path.home().joinpath('launcher.ready').write_text('ready')
    while True:
        time.sleep(1)
raise SystemExit(result)
'''
        with tempfile.TemporaryDirectory(dir='/tmp') as root, patch('dc_obf.background.Path.home', return_value=Path(root)):
            environment = os.environ.copy()
            environment['HOME'] = root
            marker = Path(root)/'background.json'
            try:
                launcher = subprocess.Popen([sys.executable, '-c', launcher_script, bot_script, 'hold'],
                    cwd=Path(__file__).resolve().parents[1], env=environment,
                    start_new_session=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    ready = Path(root)/'launcher.ready'
                    deadline = time.monotonic() + 5
                    while not ready.exists() and launcher.poll() is None and time.monotonic() < deadline:
                        time.sleep(0.02)
                    self.assertTrue(ready.exists(), 'launcher failed to start background bot')
                    # Simulate the SSH terminal/session process group hanging up.
                    os.killpg(launcher.pid, signal.SIGHUP)
                    stdout, stderr = launcher.communicate(timeout=5)
                    self.assertEqual(launcher.returncode, -signal.SIGHUP, stdout + stderr)
                finally:
                    if launcher.poll() is None:
                        launcher.terminate()
                        launcher.communicate(timeout=5)
                self.assertIn('可以關閉 SSH', stdout)
                self.assertTrue(marker.exists())
                child = json.loads(marker.read_text())
                launcher_sid = int(stdout.split('launcher-session=')[1].splitlines()[0])
                self.assertEqual(child['pid'], child['sid'])
                self.assertNotEqual(child['sid'], launcher_sid)
                # Its launcher received SIGHUP and exited; the detached bot lives.
                self.assertEqual(control.bot_state(), 'online')
                duplicate = subprocess.run([sys.executable, '-c', launcher_script, bot_script],
                    cwd=Path(__file__).resolve().parents[1], env=environment,
                    start_new_session=True, capture_output=True, text=True, timeout=8)
                self.assertEqual(duplicate.returncode, 0, duplicate.stdout + duplicate.stderr)
                self.assertIn('不會重複啟動', duplicate.stdout)
                self.assertEqual(json.loads(marker.read_text())['pid'], child['pid'])
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(control.close_bot(timeout=5), 0)
                self.assertEqual(control.bot_state(), 'offline')
                self.assertFalse(control.control_path().exists())
                self.assertIn('private background output', background.log_path().read_text())
                self.assertEqual(background.log_path().stat().st_mode & 0o777, 0o600)
            finally:
                if marker.exists() and control.running():
                    with contextlib.suppress(Exception):
                        control.close_bot(timeout=3)
