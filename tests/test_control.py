import importlib.util
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('control', Path(__file__).parents[1] / 'raspberry-pi/control.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Controls(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.control = module.Control(self.root)

    def tearDown(self):
        for owner in ('one', 'two'):
            self.control.logout(owner)
        self.tmp.cleanup()

    def test_file_escape_symlink_and_overwrite(self):
        outside = self.root.parent / 'outside-control-test'
        (self.root / 'escape').symlink_to(self.root.parent, target_is_directory=True)
        for path in ('../outside-control-test', str(outside), 'escape/outside-control-test'):
            with self.assertRaises(ValueError):
                self.control.files(dict(op='write', path=path, text='no'))
        self.control.files(dict(op='write', path='test.py', text='print(1)'))
        with self.assertRaises(ValueError):
            self.control.files(dict(op='write', path='test.py', text='print(2)'))
        self.control.files(dict(op='write', path='test.py', text='print(2)', overwrite=True))
        self.assertEqual(self.control.files(dict(op='read', path='test.py'))['text'], 'print(2)')

    def test_terminal_owner_and_real_execution(self):
        terminal = self.control.terminal(dict(op='open'), 'one')['id']
        with self.assertRaises(ValueError):
            self.control.terminal(dict(op='input', id=terminal, data='echo wrong\n'), 'two')
        self.control.terminal(dict(op='input', id=terminal, data="printf 'CONTROL_OK_%s\\n' 42\n"), 'one')
        output = ''
        for _ in range(40):
            result = self.control.terminal(dict(op='poll', id=terminal), 'one')
            output = result['output']
            if 'CONTROL_OK_42' in output:
                break
            time.sleep(.05)
        self.assertIn('CONTROL_OK_42', output)
        self.control.logout('one')
        with self.assertRaises(ValueError):
            self.control.terminal(dict(op='poll', id=terminal), 'one')

    def test_hotspot_priority_cannot_be_lowered(self):
        uuid = '4f76a4ff-5584-4180-abeb-c3651045a913'
        with patch.dict(os.environ, PI_STATION_HOTSPOT_UUID=uuid):
            with self.assertRaises(ValueError):
                self.control.network(dict(op='priority', uuid=uuid, priority=0))
            with self.assertRaises(ValueError):
                self.control.network(dict(op='priority', uuid='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', priority=999))

    def test_jobs_do_not_interpret_systemd_injection(self):
        with patch.object(self.control, 'userctl', return_value=''):
            result = self.control.jobs(dict(op='create', name='test', command='echo %h\necho second', cwd='.'))
        unit = (self.root / '.config/systemd/user' / ('pi-station-job-' + result['id'] + '.service')).read_text()
        self.assertNotIn('echo', unit)
        script = next(self.control.state.glob(result['id'] + '-*.sh'))
        self.assertIn('echo %h\necho second', script.read_text())
        with self.assertRaises(ValueError):
            self.control.jobs(dict(op='stop', id='../../sshd'))

    def test_file_job_quotes_arguments_and_update_does_not_restart(self):
        import json
        import shlex
        program = self.root / 'my program.py'
        program.write_text('print(1)')
        with patch.object(self.control, 'userctl', return_value='') as systemd:
            result = self.control.jobs(dict(op='create', kind='file', name='python',
                file=program.name, arguments='"hello world" ";touch bad"', cwd='.', autostart=True))
            key = result['id']
            saved = json.loads((self.control.state / (key + '.json')).read_text())
            self.assertEqual(shlex.split(saved['command']), ['python3', '-u', str(program), 'hello world', ';touch bad'])
            systemd.reset_mock()
            self.control.jobs(dict(op='update', id=key, name='updated', kind='command', command='echo new', cwd='.', autostart=False))
            calls = [call.args[0] for call in systemd.call_args_list]
            self.assertIn('disable', calls)
            self.assertNotIn('start', calls)
            self.assertNotIn('restart', calls)
            self.assertEqual(len(list(self.control.state.glob('*.json'))), 1)

    def test_network_edit_preserves_password_and_never_activates_connection(self):
        key = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        def nm(args, **kwargs):
            if 'modify' in args:
                return ''
            return {'connection.type': '802-11-wireless',
                    '802-11-wireless-security.key-mgmt': 'wpa-psk'}[args[4]]
        with patch.dict(os.environ, PI_STATION_HOTSPOT_UUID='bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'):
            with patch.object(self.control, 'run', side_effect=nm) as run:
                self.control.network(dict(op='update', uuid=key, name='Home', ssid='Home Wi-Fi',
                    autoconnect=True, priority=100, password=''))
                changes = run.call_args_list[-1].args[0]
                self.assertIn('modify', changes)
                self.assertNotIn('802-11-wireless-security.psk', changes)
                self.assertFalse(any('up' in call.args[0] for call in run.call_args_list))
            with patch.object(self.control, 'run', side_effect=nm) as run:
                with self.assertRaises(ValueError):
                    self.control.network(dict(op='update', uuid=key, name='Home', ssid='Home',
                        autoconnect=True, priority=100, password='short'))
                self.assertFalse(any('modify' in call.args[0] for call in run.call_args_list))

    def test_hotspot_edit_cannot_disable_auto_or_change_ssid(self):
        key = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        def nm(args, **kwargs):
            return {'connection.type': '802-11-wireless', '802-11-wireless.ssid': 'phone'}[args[4]]
        with patch.dict(os.environ, PI_STATION_HOTSPOT_UUID=key), patch.object(self.control, 'run', side_effect=nm):
            for ssid, auto in [('other', True), ('phone', False)]:
                with self.assertRaises(ValueError):
                    self.control.network(dict(op='update', uuid=key, name='phone', ssid=ssid,
                        autoconnect=auto, priority=999, password=''))
