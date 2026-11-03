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

    def terminal(self, request, owner, argv=None):
        operation = request.get('op', 'poll')
        with self.lock:
            if operation == 'open':
                if len(self.terminals) >= 8 or sum(t['owner'] == owner for t in self.terminals.values()) >= 2:
                    raise ValueError('終端機數量已達上限，請先關閉舊連線')
                master, slave = pty.openpty()
                try:
                    process = subprocess.Popen(argv or ['/bin/bash', '--noprofile', '--norc', '-i'],
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
                                seen=time.monotonic(), output='', offset=0, eof=False)
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
                return dict(ok=True, returncode=terminal['process'].returncode)
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
            returncode = terminal['process'].poll()
            return dict(output=output, cursor=terminal['offset'] + len(terminal['output']),
                        exited=returncode is not None and terminal['eof'], returncode=returncode)

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
        with self.lock:
            terminal['eof'] = True

    def execute(self, request, owner):
        operation = request.get('op', 'start')
        if operation != 'start':
            if operation not in ('poll', 'input', 'stop'):
                raise ValueError('未知執行操作')
            return self.terminal({**request, 'op': 'close' if operation == 'stop' else operation}, owner)
        import shlex
        kind = request.get('kind', 'command')
        if kind == 'file':
            name = request.get('file', '')
            if not name:
                raise ValueError('請選擇程式檔案')
            target = self.path(name)
            runner = {'.py': ['python3', '-u'], '.sh': ['bash'], '.js': ['node']}.get(target.suffix.lower())
            if not target.is_file() or not runner:
                raise ValueError('請選擇 Python、Shell 或 JavaScript 程式檔案')
            arguments = request.get('arguments', '')
            if not isinstance(arguments, str) or len(arguments) > 4000 or '\0' in arguments:
                raise ValueError('無效程式參數')
            argv = runner + [str(target)] + shlex.split(arguments)
        elif kind == 'command':
            command = request.get('command', '')
            if not isinstance(command, str) or not command.strip() or len(command) > 16000 or '\0' in command:
                raise ValueError('請輸入有效指令')
            argv = ['/bin/bash', '-lc', command]
        else:
            raise ValueError('未知執行方式')
        cwd = self.path(request.get('cwd', '.'))
        if not cwd.is_dir():
            raise ValueError('工作目錄不存在')
        return self.terminal(dict(op='open', cwd=self.relative(cwd)), owner, argv)

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
        if operation in ('create', 'update'):
            import shlex
            updating = operation == 'update'
            key = self.job_id(request) if updating else secrets.token_hex(12)
            if updating and not (self.state / (key + '.json')).is_file():
                raise ValueError('工作不存在')
            kind = request.get('kind', 'command')
            selected, arguments = '', ''
            if kind == 'file':
                selected = request.get('file', '')
                if not selected:
                    raise ValueError('請選擇程式檔案')
                target = self.path(selected)
                if not target.is_file():
                    raise ValueError('程式檔案不存在')
                runner = {'.py': ['python3', '-u'], '.sh': ['bash'], '.js': ['node']}.get(target.suffix.lower())
                if not runner:
                    raise ValueError('支援 Python、Shell、JavaScript；其他類型請使用指令')
                arguments = request.get('arguments', '')
                if not isinstance(arguments, str) or len(arguments) > 4000:
                    raise ValueError('程式參數過長')
                command = shlex.join(runner + [str(target)] + shlex.split(arguments))
                selected = self.relative(target)
            elif kind == 'command':
                command = request.get('command')
            else:
                raise ValueError('未知工作類型')
            name = request.get('name', '')
            if not isinstance(command, str) or not command.strip() or len(command) > 16000:
                raise ValueError('請輸入程式指令（最多 16000 字元）')
            if not isinstance(name, str) or not name.strip() or len(name) > 100:
                raise ValueError('請輸入工作名稱（最多 100 字元）')
            if not updating and len(list(self.state.glob('*.json'))) >= 50:
                raise ValueError('背景工作最多 50 個')
            cwd = self.path(request.get('cwd', '.'))
            if not cwd.is_dir():
                raise ValueError('工作目錄不存在')
            data = dict(id=key, name=name, command=command, kind=kind, file=selected,
                        arguments=arguments, cwd=self.relative(cwd),
                        autostart=request.get('autostart') is True)
            # 以腳本保存使用者指令，避免 systemd 將 % 或換行解讀為 unit 語法。
            import shlex
            script = self.state / (key + '-' + secrets.token_hex(4) + '.sh')
            script.write_text('#!/bin/bash\ncd -- ' + shlex.quote(str(cwd)) + ' || exit 1\n' + command + '\n')
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
            else:
                self.userctl('disable', 'pi-station-job-' + key)
            if not updating:
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
        def field(key, name):
            return self.run(['nmcli', '--escape', 'no', '-g', name,
                             'connection', 'show', 'uuid', key])
        if operation == 'list':
            profiles = []
            rows = self.run(['nmcli', '-t', '-f', 'UUID,TYPE', 'connection', 'show'])
            for row in rows.splitlines():
                key, _, kind = row.partition(':')
                if kind in ('wifi', '802-11-wireless'):
                    profiles.append(dict(uuid=key, name=field(key, 'connection.id')))
            return dict(profiles=profiles,
                        current=self.run(['nmcli', '-f', 'GENERAL.CONNECTION,IP4.ADDRESS,IP4.GATEWAY',
                                          'device', 'show', 'wlan0']),
                        saved=self.run(['nmcli', '-f', 'NAME,UUID,TYPE,AUTOCONNECT,AUTOCONNECT-PRIORITY',
                                        'connection', 'show']),
                        nearby=self.run(['nmcli', '-f', 'IN-USE,SSID,SIGNAL,SECURITY', 'device', 'wifi',
                                         'list', 'ifname', 'wlan0', '--rescan', 'no']))
        key = request.get('uuid', '')
        if not isinstance(key, str) or not re.fullmatch(r'[a-f0-9-]{36}', key):
            raise ValueError('無效網路 UUID')
        hotspot = os.environ.get('PI_STATION_HOTSPOT_UUID')
        if not hotspot:
            raise ValueError('尚未設定手機熱點 UUID')
        if operation == 'priority':
            priority = int(request.get('priority', 0))
            if key == hotspot or not -999 <= priority <= 998:
                raise ValueError('手機熱點維持最高 999；其他網路可設 -999 至 998')
        if field(key, 'connection.type') != '802-11-wireless':
            raise ValueError('只允許編輯 Wi-Fi')
        if operation == 'read':
            security = field(key, '802-11-wireless-security.key-mgmt')
            result = dict(uuid=key, name=field(key, 'connection.id'),
                          ssid=field(key, '802-11-wireless.ssid'),
                          autoconnect=field(key, 'connection.autoconnect') == 'yes',
                          priority=int(field(key, 'connection.autoconnect-priority')),
                          security=security or 'open', hotspot=key == hotspot)
            if security in ('wpa-eap', 'wpa-eap-suite-b-192'):
                result['identity'] = field(key, '802-1x.identity')
            return result
        if operation == 'priority':
            changes = ['connection.autoconnect-priority', str(priority)]
        elif operation == 'update':
            name, ssid = request.get('name'), request.get('ssid')
            if not isinstance(name, str) or not name.strip() or len(name) > 100 or any(c in name for c in '\n\r\0'):
                raise ValueError('無效設定名稱')
            if not isinstance(ssid, str) or not 1 <= len(ssid.encode()) <= 32 or any(c in ssid for c in '\n\r\0'):
                raise ValueError('SSID 長度需為 1 至 32 bytes')
            auto = request.get('autoconnect')
            if not isinstance(auto, bool):
                raise ValueError('無效自動連線設定')
            priority = int(request.get('priority', 0))
            if key == hotspot:
                if priority != 999 or not auto or ssid != field(key, '802-11-wireless.ssid'):
                    raise ValueError('手機熱點的 SSID、自動連線與最高優先序不可變更')
            elif not -999 <= priority <= 998:
                raise ValueError('優先序需為 -999 至 998')
            changes = ['connection.id', name, '802-11-wireless.ssid', ssid,
                       'connection.autoconnect', 'yes' if auto else 'no',
                       'connection.autoconnect-priority', str(priority)]
            password = request.get('password', '')
            if not isinstance(password, str) or any(c in password for c in '\n\r\0'):
                raise ValueError('無效 Wi-Fi 密碼')
            security = field(key, '802-11-wireless-security.key-mgmt')
            if security in ('wpa-eap', 'wpa-eap-suite-b-192'):
                identity = request.get('identity', '')
                if not isinstance(identity, str) or not identity or any(c in identity for c in '\n\r\0'):
                    raise ValueError('請輸入企業網路帳號')
                changes += ['802-1x.identity', identity]
                if password:
                    changes += ['802-1x.password', password]
            elif password:
                if security == 'wpa-psk':
                    if not (8 <= len(password.encode()) <= 63 or re.fullmatch(r'[0-9A-Fa-f]{64}', password)):
                        raise ValueError('WPA 密碼需為 8 至 63 bytes，或 64 位十六進位金鑰')
                elif security == 'sae':
                    if not 1 <= len(password.encode()) <= 63:
                        raise ValueError('WPA3 密碼需為 1 至 63 bytes')
                else:
                    raise ValueError('這個網路不支援在此修改 Wi-Fi 密碼')
                changes += ['802-11-wireless-security.psk', password]
        else:
            raise ValueError('未知網路操作')
        # 錯誤訊息不可帶出包含密碼的 nmcli 參數。
        try:
            self.run(['nmcli', 'connection', 'modify', 'uuid', key, *changes])
        except (ValueError, subprocess.SubprocessError):
            raise ValueError('儲存失敗，請確認欄位與 NetworkManager 權限') from None
        return dict(ok=True)

    def dispatch(self, action, request, owner):
        if action == 'system':
            return self.system()
        if action == 'files':
            return self.files(request)
        if action == 'terminal':
            return self.terminal(request, owner)
        if action == 'execute':
            return self.execute(request, owner)
        if action == 'jobs':
            return self.jobs(request)
        if action == 'network':
            return self.network(request)
        raise ValueError('未知操作')
