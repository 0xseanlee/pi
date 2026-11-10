"""Fetch, build and test an isolated release before atomically activating it."""
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import uuid

REPOSITORY = 'https://github.com/0xseanlee/pi.git'
BRANCH = 'main'


@contextlib.contextmanager
def lock(name):
    directory = Path.home() / '.config/dc'
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    fd = os.open(directory / name, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('OBF 正在執行或更新，請等它結束後再試。') from None
        yield
    finally:
        os.close(fd)


def execute(command, *, cwd=None, capture=False, timeout=180):
    environment = os.environ.copy()
    environment['GIT_TERMINAL_PROMPT'] = '0'
    environment.pop('PYTHONPATH', None)
    result = subprocess.run(command, cwd=cwd, env=environment, capture_output=capture, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError('更新檢查未通過，舊版仍然保留。')
    return result.stdout.strip() if capture else None


def activate(root, release):
    if not (release / '.ready').is_file():
        raise RuntimeError('拒絕啟用未完成測試的版本。')
    current = root / 'current'
    if current.is_symlink():
        previous = root / ('.previous-' + uuid.uuid4().hex)
        previous.symlink_to(os.readlink(current))
        os.replace(previous, root / 'previous')
    temporary = root / ('.current-' + uuid.uuid4().hex)
    temporary.symlink_to(release)
    os.replace(temporary, current)


def update():
    os.umask(0o077)
    root = Path.home() / '.local/share/dc-obf'
    releases = root / 'releases'
    releases.mkdir(parents=True, exist_ok=True)
    with lock('obf.update.lock'), lock('obf.run.lock'):
        print('從 0xseanlee/pi 抓取更新…', flush=True)
        with tempfile.TemporaryDirectory(prefix='.fetch-', dir=root) as temporary:
            checkout = Path(temporary) / 'repo'
            execute(['git', 'clone', '--quiet', '--depth', '1', '--branch', BRANCH, REPOSITORY, str(checkout)])
            commit = execute(['git', 'rev-parse', 'HEAD'], cwd=checkout, capture=True)
            if not re.fullmatch('[0-9a-f]{40}', commit):
                raise RuntimeError('Git 版本格式不正確，未啟用。')
            release = releases / commit
            if not (release / '.ready').is_file():
                if release.exists():
                    if (root / 'current').is_symlink() and (root / 'current').resolve() == release:
                        raise RuntimeError('目前版本狀態異常，已停止更新。')
                    shutil.rmtree(release)  # Only a commit-named incomplete managed release.
                release.mkdir()
                (release / '.building').touch()
                checkout.rename(release / 'source')
                package = release / 'source/dc-obf'
                if not (package / 'pyproject.toml').is_file():
                    raise RuntimeError('repo 缺少 dc-obf 程式，保留目前版本。')
                environment = release / 'venv'
                print('建立獨立環境並測試新版…', flush=True)
                execute([sys.executable, '-m', 'venv', str(environment)])
                python = str(environment / 'bin/python')
                execute([python, '-m', 'pip', 'install', '--quiet', str(package)], timeout=300)
                execute([python, '-m', 'dc_obf.bootstrap_backend'], timeout=90)
                execute([python, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], cwd=package)
                execute([python, '-m', 'dc_obf.cli', 'obf', '--help'], capture=True)
                (release / '.ready').write_text(json.dumps({'commit': commit, 'repository': REPOSITORY}) + '\n')
                (release / '.building').unlink(missing_ok=True)
            if not ((root / 'current').is_symlink() and (root / 'current').resolve() == release):
                activate(root, release)
            if hasattr(os, 'sync'):
                os.sync()
            print('更新完成：' + commit[:12] + '。Bot 沒有自動啟動；使用時執行 dc obf。', flush=True)
    return 0
