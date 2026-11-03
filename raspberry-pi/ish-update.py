#!/usr/bin/env python3
"""Run in iSH: locate this Pi by its pinned SSH key and install an update."""
import base64
from concurrent.futures import ThreadPoolExecutor
import getpass
import hashlib
import ipaddress
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile

FINGERPRINT = 'SHA256:eNrWqeNIU5Q/V8g+E05LuBisFDPbHYC0JjIFrNjqMtQ'


def locate(address):
    try:
        with socket.create_connection((address, 22), timeout=.7):
            pass
        result = subprocess.run(['ssh-keyscan', '-T', '2', '-t', 'ed25519', address],
                                capture_output=True, text=True, timeout=4)
        for row in result.stdout.splitlines():
            parts = row.split()
            if len(parts) < 3 or parts[1] != 'ssh-ed25519':
                continue
            digest = base64.b64encode(hashlib.sha256(base64.b64decode(parts[2], validate=True)).digest()).decode().rstrip('=')
            if 'SHA256:' + digest == FINGERPRINT:
                return address, 'pi-station-sean ssh-ed25519 ' + parts[2] + '\n'
    except (OSError, ValueError, subprocess.SubprocessError):
        pass


def find_pi():
    groups = [['sean.local'], ['172.20.10.' + str(n) for n in range(2, 15)]]
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # UDP connect only selects a route; it does not send a packet.
            s.connect(('1.1.1.1', 80))
            own = ipaddress.ip_address(s.getsockname()[0])
        if own.is_private and not own.is_loopback and not own.is_unspecified:
            groups.append([str(ip) for ip in ipaddress.ip_network(str(own) + '/24', strict=False).hosts() if ip != own])
    except OSError:
        pass
    for group in groups:
        print('正在搜尋樹莓派……', file=sys.stderr, flush=True)
        with ThreadPoolExecutor(max_workers=20) as pool:
            for result in pool.map(locate, group):
                if result:
                    return result
    raise RuntimeError('NO result：找不到已確認 SSH 金鑰的樹莓派；請確認同一網路及 SSH 已開啟。')


def main():
    version = sys.argv[1]
    if len(version) != 40 or any(c not in '0123456789abcdef' for c in version):
        raise ValueError('無效更新版本')
    address, key = find_pi()
    print('已確認樹莓派：' + address, file=sys.stderr)
    path = Path('/root/pwd/pi.txt')
    password = path.read_text().rstrip('\r\n') if path.is_file() else ''
    if not password:
        password = getpass.getpass('樹莓派密碼：')
    url = 'https://raw.githubusercontent.com/0xseanlee/pi/' + version + '/raspberry-pi/update-console.py'
    command = ("sudo -S -p '' -v && "
        't=$(mktemp) && curl -fsSL --max-time 120 ' + url + ' -o "$t" && '
        'sudo -n python3 "$t" ' + version + ' </dev/null; r=$?; '
        '[ -z "$t" ] || rm -f "$t"; exit "$r"')
    with tempfile.NamedTemporaryFile(mode='w') as known:
        known.write(key)
        known.flush()
        result = subprocess.run(['ssh', '-o', 'ConnectTimeout=10', '-o', 'HostKeyAlias=pi-station-sean',
            '-o', 'StrictHostKeyChecking=yes', '-o', 'HostKeyAlgorithms=ssh-ed25519',
            '-o', 'UserKnownHostsFile=' + known.name, 'sean@' + address, command],
            input=(password + '\n').encode(), capture_output=True, timeout=300)
    password = ''
    return ('樹莓派 IP：' + address + '\n' + result.stdout.decode(errors='replace') +
            '\n診斷訊息：\n' + result.stderr.decode(errors='replace') + '\n退出碼：' + str(result.returncode))


if __name__ == '__main__':
    try:
        result = main()
    except Exception as error:
        result = 'NO result\n' + str(error)
    data = ('更新結果：\n' + result).encode()
    fd = os.open('/dev/clipboard', os.O_WRONLY | os.O_TRUNC)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    print('結果已複製到剪貼簿。', file=sys.stderr)
