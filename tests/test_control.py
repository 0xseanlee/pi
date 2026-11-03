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
        self.assertIn('echo %h\necho second', (self.control.state / (result['id'] + '.sh')).read_text())
        with self.assertRaises(ValueError):
            self.control.jobs(dict(op='stop', id='../../sshd'))
