import pathlib
import sys
import tempfile
import unittest

from dc_obf.engine import EngineError, transform


class EngineTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_engine_is_not_fake_success(self):
        with self.assertRaises(EngineError):
            await transform([], '/unused/input.lua', '/unused/output.lua')

    async def test_identical_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            source = pathlib.Path(root) / 'input.lua'
            output = pathlib.Path(root) / 'out.lua'
            source.write_text('print(1)')
            script = 'import pathlib,sys; pathlib.Path(sys.argv[2]).write_bytes(pathlib.Path(sys.argv[1]).read_bytes())'
            with self.assertRaises(EngineError):
                await transform([sys.executable, '-c', script, '{input}', '{output}'], source, output)

    async def test_timeout_stops_worker(self):
        with tempfile.TemporaryDirectory() as root:
            source = pathlib.Path(root) / 'input.lua'
            source.write_text('print(1)')
            with self.assertRaisesRegex(EngineError, '逾時'):
                await transform([sys.executable, '-c', 'import time; time.sleep(10)', '{input}', '{output}'], source,
                                pathlib.Path(root) / 'output.lua', timeout=0.05)
