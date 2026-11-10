import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

from dc_obf.bootstrap_backend import vendor_path
from dc_obf.engine import transform


@unittest.skipUnless(shutil.which('lua5.1') and (vendor_path()/'cli.lua').is_file(), 'Pinned backend not installed here')
class VMFixtures(unittest.IsolatedAsyncioTestCase):
    async def test_vm_preserves_closures_varargs_and_returns(self):
        source_code = '''
local function pack(...) return {n=select('#',...),...} end
local function make(n) return function(x) n=n+x; return n,nil,42 end end
local f=make(7)
local t=pack(f(5))
print(t.n,t[1],t[2],t[3])
print(f(2))
'''
        with tempfile.TemporaryDirectory() as directory:
            source=pathlib.Path(directory)/'input.lua'; output=pathlib.Path(directory)/'protected.lua'
            source.write_text(source_code)
            await transform([sys.executable,'-m','dc_obf.prometheus_adapter','{input}','{output}'],source,output)
            before=subprocess.run(['lua5.1',str(source)],capture_output=True,text=True,timeout=10)
            after=subprocess.run(['lua5.1',str(output)],capture_output=True,text=True,timeout=10)
            self.assertEqual(before.returncode,0)
            self.assertEqual(after.returncode,0,after.stderr)
            self.assertEqual(before.stdout,after.stdout)
            self.assertNotEqual(source.read_bytes(),output.read_bytes())
