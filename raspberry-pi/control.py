"""Authenticated controls, executed with the existing sean service identity."""
import base64
import codecs
import json
import os
from pathlib import Path
import pty
import re
import secrets
import signal
import socket
import subprocess
import threading
import time

LIMIT = 8 * 1024 * 1024


class Control:
    def __init__(self, root=None):
        self.root = Path(root or Path.home()).resolve()
        self.state = self.root / '.local/state/pi-station'
        self.terminals = {}
        self.lock = threading.RLock()
        threading.Thread(target=self.reap, daemon=True).start()

    def path(self, name='.'):
        if not isinstance(name, str) or '\0' in name:
            raise ValueError('無效路徑')
        path = (self.root / name).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError('檔案操作範圍為 sean 的家目錄')
        return path

    def relative(self, path):
        return str(path.relative_to(self.root))

    def run(self, args, timeout=12):
        result = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
        if result.returncode:
            raise ValueError((result.stderr or result.stdout or '操作失敗')[-2000:])
        return result.stdout.strip()

    def system(self):
        disk = os.statvfs(self.root)
        mem = {}
        for row in Path('/proc/meminfo').read_text().splitlines():
            key, value = row.split(':', 1)
            mem[key] = int(value.split()[0]) * 1024
        return dict(hostname=socket.gethostname(), load=os.getloadavg()[0],
                    memory_total=mem['MemTotal'], memory_available=mem['MemAvailable'],
                    disk_total=disk.f_blocks * disk.f_frsize,
                    disk_available=disk.f_bavail * disk.f_frsize,
                    home=str(self.root))

    def files(self, request):
        path = self.path(request.get('path', '.'))
        operation = request.get('op', 'list')
        if operation == 'list':
            entries = []
            for item in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                try:
                    target = self.path(self.relative(item))
                    info = target.stat()
                    entries.append(dict(name=item.name, path=self.relative(item),
                                        directory=target.is_dir(), size=info.st_size))
                except (ValueError, OSError):
                    continue
                if len(entries) >= 2000:
                    break
            return dict(path=self.relative(path), entries=entries)
        if operation in ('read', 'download'):
            with path.open('rb') as f:
                content = f.read(LIMIT + 1)
            if len(content) > LIMIT:
                raise ValueError('單檔上限 8 MiB，較大檔案請使用 SSH/SCP')
            if operation == 'read':
                return dict(path=self.relative(path), text=content.decode('utf-8'))
            return dict(name=path.name, data=base64.b64encode(content).decode())
        if operation == 'mkdir':
            path.mkdir()
        elif operation in ('write', 'upload'):
            if operation == 'write':
                content = request['text'].encode('utf-8')
            else:
                content = base64.b64decode(request['data'], validate=True)
            if len(content) > LIMIT:
                raise ValueError('單檔上限 8 MiB')
            # 新檔預設不可覆寫；編輯既有文字檔則明確允許覆寫。
            overwrite = operation == 'write' and request.get('overwrite') is True
            if path.exists() and not overwrite:
                raise ValueError('同名檔案已存在，請改名或使用編輯器')
            if path.exists() and not path.is_file():
                raise ValueError('不是一般檔案')
            mode = (path.stat().st_mode & 0o777) if path.exists() else 0o600
            temp = path.parent / ('.pi-upload-' + secrets.token_hex(12))
            try:
                with temp.open('xb') as f:
                    f.write(content)
                temp.chmod(mode)
                if overwrite:
                    os.replace(temp, path)
                else:
                    os.link(temp, path)
            finally:
                temp.unlink(missing_ok=True)
        elif operation == 'rename':
            target = self.path(request['target'])
            if path == self.root or target.exists():
                raise ValueError('無法改名：目標已存在或是家目錄')
            path.rename(target)
        else:
            raise ValueError('未知檔案操作')
        return dict(ok=True)

    def reap(self):
        while True:
            time.sleep(30)
            with self.lock:
                stale = [key for key, t in self.terminals.items()
                         if time.monotonic() - t['seen'] > 900]
                for key in stale:
                    self.close_terminal(key)

    def close_terminal(self, key):
        terminal = self.terminals.pop(key, None)
        if terminal:
            try:
                os.killpg(terminal['process'].pid, signal.SIGHUP)
            except ProcessLookupError:
                pass
            try:
                os.close(terminal['fd'])
            except OSError:
                pass
            try:
                terminal['process'].wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(terminal['process'].pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                terminal['process'].wait(timeout=2)

    def logout(self, owner):
        with self.lock:
            for key in [key for key, t in self.terminals.items() if t['owner'] == owner]:
                self.close_terminal(key)

    def terminal(self, request, owner):
        operation = request.get('op', 'poll')
        with self.lock:
            if operation == 'open':
                if len(self.terminals) >= 8 or sum(t['owner'] == owner for t in self.terminals.values()) >= 2:
                    raise ValueError('終端機數量已達上限，請先關閉舊連線')
                master, slave = pty.openpty()
                try:
                    process = subprocess.Popen(['/bin/bash', '--noprofile', '--norc', '-i'],
                        stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
                        cwd=self.path(request.get('cwd', '.')),
                        env={**os.environ, 'TERM': 'dumb', 'PS1': 'sean@pi:\\w $ ',
                             'HISTFILE': '/dev/null'})
                except Exception:
                    os.close(master)
                    raise
                finally:
                    os.close(slave)
                key = secrets.token_urlsafe(24)
                terminal = dict(owner=owner, fd=master, process=process,
                                seen=time.monotonic(), output='', offset=0)
                self.terminals[key] = terminal
                threading.Thread(target=self.read_terminal, args=(key, terminal), daemon=True).start()
                return dict(id=key)
            key = request.get('id')
            terminal = self.terminals.get(key)
            if not terminal or terminal['owner'] != owner:
                raise ValueError('終端機不存在或不屬於目前登入')
            terminal['seen'] = time.monotonic()
            if operation == 'close':
                self.close_terminal(key)
                return dict(ok=True)
            if operation == 'input':
                data = request.get('data', '')
                if not isinstance(data, str) or len(data.encode()) > 4096:
                    raise ValueError('單次輸入過長')
                if data == '\x03':
                    os.killpg(terminal['process'].pid, signal.SIGINT)
                else:
                    os.write(terminal['fd'], data.encode())
            elif operation != 'poll':
                raise ValueError('未知終端機操作')
            cursor = max(int(request.get('cursor', 0)), terminal['offset'])
            output = terminal['output'][cursor - terminal['offset']:]
            return dict(output=output, cursor=terminal['offset'] + len(terminal['output']),
                        exited=terminal['process'].poll() is not None)

    def read_terminal(self, key, terminal):
        decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        while True:
            try:
                chunk = os.read(terminal['fd'], 4096)
                if not chunk:
                    break
            except OSError:
                break
            with self.lock:
                if self.terminals.get(key) is not terminal:
                    break
                terminal['output'] += decoder.decode(chunk)
                trim = max(0, len(terminal['output']) - 262144)
                terminal['output'] = terminal['output'][trim:]
                terminal['offset'] += trim

    def userctl(self, *args):
        return self.run(['systemctl', '--user', *args])

    def job_id(self, request):
        key = request.get('id', '')
        if not isinstance(key, str) or not re.fullmatch(r'[a-f0-9]{24}', key):
            raise ValueError('無效工作 ID')
        return key

    def jobs(self, request):
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        operation = request.get('op', 'list')
        if operation == 'list':
            results = []
            for file in sorted(self.state.glob('*.json')):
                data = json.loads(file.read_text())
                key = self.job_id(data)
                state = subprocess.run(['systemctl', '--user', 'is-active', 'pi-station-job-' + key],
                                       text=True, capture_output=True, timeout=8).stdout.strip()
                results.append({**data, 'state': state})
            return dict(jobs=results)
        if operation == 'create':
            command, name = request.get('command'), request.get('name', '')
            if not isinstance(command, str) or not command.strip() or len(command) > 16000:
                raise ValueError('請輸入程式指令（最多 16000 字元）')
            if not isinstance(name, str) or not name.strip() or len(name) > 100:
                raise ValueError('請輸入工作名稱（最多 100 字元）')
            if len(list(self.state.glob('*.json'))) >= 50:
                raise ValueError('背景工作最多 50 個')
            cwd = self.path(request.get('cwd', '.'))
            if not cwd.is_dir():
                raise ValueError('工作目錄不存在')
            key = secrets.token_hex(12)
            data = dict(id=key, name=name, command=command, cwd=self.relative(cwd),
                        autostart=request.get('autostart') is True)
            # 以腳本保存使用者指令，避免 systemd 將 % 或換行解讀為 unit 語法。
            import shlex
            script = self.state / (key + '.sh')
            script.write_text('#!/bin/bash\ncd -- ' + shlex.quote(str(cwd)) + '\n' + command + '\n')
            script.chmod(0o700)
            units = self.root / '.config/systemd/user'
            units.mkdir(parents=True, exist_ok=True)
            executable = str(script).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%')
            unit = ('[Unit]\nDescription=Pi Station background job\n[Service]\n'
                    'Type=simple\nExecStart=/bin/bash "' + executable + '"\n'
                    'Restart=on-failure\nRestartSec=5\n[Install]\nWantedBy=default.target\n')
            (units / ('pi-station-job-' + key + '.service')).write_text(unit)
            (self.state / (key + '.json')).write_text(json.dumps(data))
            self.userctl('daemon-reload')
            if data['autostart']:
                self.userctl('enable', 'pi-station-job-' + key)
            self.userctl('start', 'pi-station-job-' + key)
            return dict(ok=True, id=key)
        key = self.job_id(request)
        if not (self.state / (key + '.json')).is_file():
            raise ValueError('工作不存在')
        unit = 'pi-station-job-' + key
        if operation == 'logs':
            return dict(output=self.run(['journalctl', '--user', '-u', unit, '-n', '150', '--no-pager']))
        if operation in ('start', 'stop', 'restart'):
            self.userctl(operation, unit)
            return dict(ok=True)
        raise ValueError('未知工作操作')

    def network(self, request):
        operation = request.get('op', 'list')
        if operation == 'list':
            return dict(current=self.run(['nmcli', '-f', 'GENERAL.CONNECTION,IP4.ADDRESS,IP4.GATEWAY',
                                          'device', 'show', 'wlan0']),
                        saved=self.run(['nmcli', '-f', 'NAME,UUID,TYPE,AUTOCONNECT,AUTOCONNECT-PRIORITY',
                                        'connection', 'show']),
                        nearby=self.run(['nmcli', '-f', 'IN-USE,SSID,SIGNAL,SECURITY', 'device', 'wifi',
                                         'list', 'ifname', 'wlan0', '--rescan', 'no']))
        if operation == 'priority':
            key = request.get('uuid', '')
            if not isinstance(key, str) or not re.fullmatch(r'[a-f0-9-]{36}', key):
                raise ValueError('無效網路 UUID')
            hotspot = os.environ.get('PI_STATION_HOTSPOT_UUID')
            if not hotspot:
                raise ValueError('尚未設定手機熱點 UUID，無法修改優先序')
            priority = int(request.get('priority', 0))
            if key == hotspot or not -999 <= priority <= 998:
                raise ValueError('手機熱點維持最高 999；其他網路可設 -999 至 998')
            kind = self.run(['nmcli', '-g', 'connection.type', 'connection', 'show', 'uuid', key])
            if kind != '802-11-wireless':
                raise ValueError('只允許修改 Wi-Fi 優先序')
            self.run(['nmcli', 'connection', 'modify', 'uuid', key,
                      'connection.autoconnect-priority', str(priority)])
            return dict(ok=True)
        raise ValueError('未知網路操作')

    def dispatch(self, action, request, owner):
        if action == 'system':
            return self.system()
        if action == 'files':
            return self.files(request)
        if action == 'terminal':
            return self.terminal(request, owner)
        if action == 'jobs':
            return self.jobs(request)
        if action == 'network':
            return self.network(request)
        raise ValueError('未知操作')
