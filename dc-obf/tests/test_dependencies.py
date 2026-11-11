import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from dc_obf import dependencies as dep


class DependencyTests(unittest.TestCase):
    def package(self, root):
        p=Path(root)/'package'; p.mkdir()
        (p/'pyproject.toml').write_text('[build-system]\nrequires=["setuptools>=68"]\n[project]\ndependencies=["discord.py==2.7.1"]\n')
        return p

    def test_verified_cache_avoids_network(self):
        with tempfile.TemporaryDirectory() as root:
            package=self.package(root); cache=Path(root)/'cache'
            target=cache/dep.cache_key(dep.requirements(package)); target.mkdir(parents=True)
            wheel=target/'fixture.whl';wheel.write_bytes(b'fixture')
            (target/'.ready.json').write_text(json.dumps({wheel.name:dep.digest(wheel)}))
            with patch('dc_obf.dependencies.pip') as pip:
                self.assertEqual(dep.prepare_wheels('/python',package,cache),target)
                pip.assert_not_called()

    def test_corrupt_cache_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root); p=root/'fixture.whl'; p.write_bytes(b'first')
            (root/'.ready.json').write_text(json.dumps({p.name:dep.digest(p)}))
            p.write_bytes(b'corrupt')
            self.assertFalse(dep.valid_cache(root))

    def test_failed_download_never_marks_cache_ready(self):
        with tempfile.TemporaryDirectory() as root:
            package=self.package(root);cache=Path(root)/'cache'
            with patch('dc_obf.dependencies.pip',side_effect=dep.DependencyError('network')):
                with self.assertRaises(dep.DependencyError):
                    dep.prepare_wheels('/python',package,cache)
            self.assertEqual(list(cache.glob('*/.ready.json')),[])

    def test_pip_failure_preserves_tls_and_has_actionable_error(self):
        with patch.dict(os.environ,{'PIP_EXTRA_INDEX_URL':'https://other.invalid/simple','PIP_CERT':'/certificate.pem'}), patch(
            'dc_obf.dependencies.subprocess.run',return_value=subprocess.CompletedProcess([],1)
        ) as run:
            with self.assertRaisesRegex(dep.DependencyError,'舊版仍可用'):
                dep.pip('/python',['download','a-package'])
            arguments=run.call_args.args[0]; env=run.call_args.kwargs['env']
            self.assertNotIn('--trusted-host',arguments)
            self.assertEqual(env['PIP_CERT'],'/certificate.pem')
            self.assertEqual(env['PIP_INDEX_URL'],'https://pypi.org/simple')
            self.assertEqual(env['PIP_EXTRA_INDEX_URL'],'')

    def test_build_and_install_use_no_index(self):
        with tempfile.TemporaryDirectory() as root, patch('dc_obf.dependencies.prepare_wheels',return_value=Path(root)/'cache'), patch(
            'dc_obf.dependencies.pip'
        ) as pip:
            release=Path(root)/'release';release.mkdir()
            def build(python,args,**kwargs):
                if args[0]=='wheel':
                    (release/'built-wheels/dc_obf-0.1.0-py3-none-any.whl').write_bytes(b'fixture')
            pip.side_effect=build
            dep.install_release('/python','/package',release,'/cache')
            for call in pip.call_args_list[:2]:self.assertIn('--no-index',call.args[1])
