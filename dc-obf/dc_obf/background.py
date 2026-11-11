"""Start an on-demand process without a terminal or SSH session dependency."""
import os
from pathlib import Path
import stat
import subprocess
import sys
import time

from .control import bot_state
from .updater import lock

STATES = {'offline': '已關閉', 'connecting': '背景連線中', 'online': '已上線',
          'processing': '正在處理工作', 'stopping': '停止中', 'busy': '執行／更新／設定中'}


def log_path():
    return Path.home() / '.local/state/dc-obf/bot.log'


def start_background(*, command=None, timeout=5):
    with lock('obf.launch.lock'):
        state = bot_state()
        if state in ('connecting', 'online', 'processing'):
            print('OBF 已在執行（' + STATES[state] + '），不會重複啟動。可直接離開 SSH。')
            return 0
        if state != 'offline':
            raise RuntimeError('OBF ' + STATES[state] + '，請稍後再試。')
        path = log_path()
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        path.parent.chmod(0o700)
        fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise RuntimeError('OBF 記錄檔必須是本帳號持有的一般檔案。')
            os.fchmod(fd, 0o600)
            environment = os.environ.copy()
            environment.pop('PYTHONPATH', None)
            # Use this release's interpreter/code, never the caller's old cwd.
            process = subprocess.Popen(
                command or [sys.executable, '-m', 'dc_obf.cli', 'obf', '--foreground'],
                cwd=Path(__file__).resolve().parent.parent, env=environment,
                stdin=subprocess.DEVNULL, stdout=fd, stderr=fd,
                start_new_session=True, close_fds=True, umask=0o077,
            )
        finally:
            os.close(fd)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f'OBF 背景啟動未完成，請查看 {path}。')
            state = bot_state()
            if state in ('connecting', 'online', 'processing'):
                print('OBF 背景已啟動（' + STATES[state] + '）。現在可以關閉 SSH。')
                print('查狀態：dc obf --status；停止：dc obf --close。')
                print('處理一份工作後自動下線。記錄：' + str(path))
                return 0
            time.sleep(0.05)
        # The process may still initialize; report that honestly without spawning
        # a duplicate or killing a process by a possibly recycled PID.
        raise RuntimeError(f'背景程序已啟動，但尚未確認控制端就緒；請用 dc obf --status 或查看 {path}。')
