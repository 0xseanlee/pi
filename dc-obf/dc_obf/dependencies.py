"""Cache verified dependency wheels, then build/install releases without an index."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import tomllib


class DependencyError(RuntimeError):
    pass


def requirements(package):
    with (Path(package) / 'pyproject.toml').open('rb') as source:
        metadata = tomllib.load(source)
    return sorted(set(metadata['build-system']['requires'] + metadata['project'].get('dependencies', []) + ['wheel']))


def cache_key(required):
    identity = [required, sys.implementation.cache_tag, sysconfig.get_platform()]
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def valid_cache(directory):
    try:
        manifest = json.loads((directory / '.ready.json').read_text())
        if not isinstance(manifest, dict) or not manifest:
            return False
        return all(
            Path(name).name == name and name.endswith('.whl')
            and (directory / name).is_file() and digest(directory / name) == expected
            for name, expected in manifest.items()
        )
    except (OSError, ValueError, TypeError):
        return False


def pip(python, arguments, timeout=300):
    environment = os.environ.copy()
    environment.pop('PYTHONPATH', None)
    # These are local to this update process; do not alter the user's pip config.
    # Keep TLS verification, certificate and proxy settings enabled.
    environment['PIP_CONFIG_FILE'] = os.devnull
    environment['PIP_INDEX_URL'] = 'https://pypi.org/simple'
    environment['PIP_EXTRA_INDEX_URL'] = ''
    environment.pop('PIP_NO_INDEX', None)
    environment.pop('PIP_FIND_LINKS', None)
    command = [str(python), '-m', 'pip', '--disable-pip-version-check', *arguments]
    try:
        result = subprocess.run(command, env=environment, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        raise DependencyError('套件下載或安裝逾時／中斷；更新未啟用，舊版仍可用。請換較穩定的網路後重試。') from None
    if result.returncode:
        raise DependencyError('套件準備失敗；更新未啟用，舊版仍可用。請確認網路能連到 PyPI 後重試。')


def prepare_wheels(python, package, cache_root):
    required = requirements(package)
    cache_root = Path(cache_root)
    cache_root.mkdir(parents=True, exist_ok=True)
    target = cache_root / cache_key(required)
    if valid_cache(target):
        print('使用已驗證的本機套件快取。', flush=True)
        return target
    print('首次準備依賴套件快取（需要連線 PyPI）…', flush=True)
    with tempfile.TemporaryDirectory(prefix='.wheels-', dir=cache_root) as temporary:
        staging = Path(temporary)
        pip(python, ['download', '--no-input', '--progress-bar', 'off', '--only-binary=:all:',
                     '--retries', '5', '--timeout', '20', '--dest', str(staging), *required])
        wheels = sorted(staging.glob('*.whl'))
        if not wheels:
            raise DependencyError('沒有取得套件，保留舊版。')
        (staging / '.ready.json').write_text(json.dumps({p.name: digest(p) for p in wheels}) + '\n')
        if target.exists():
            shutil.rmtree(target)  # Only this updater's invalid dependency cache.
        staging.rename(target)
    return target


def install_release(python, package, release, cache_root):
    wheels = prepare_wheels(python, package, cache_root)
    built = Path(release) / 'built-wheels'
    built.mkdir()
    print('從本機套件建置與安裝新版，不再查詢套件站…', flush=True)
    pip(python, ['wheel', '--no-index', '--find-links', str(wheels), '--no-deps',
                 '--wheel-dir', str(built), str(package)])
    products = list(built.glob('dc_obf-*.whl'))
    if len(products) != 1:
        raise DependencyError('新版程式封裝不完整，保留舊版。')
    pip(python, ['install', '--no-index', '--find-links', str(wheels), str(products[0])])
    pip(python, ['check'])
