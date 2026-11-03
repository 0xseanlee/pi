#!/usr/bin/env python3
"""Local SSH authentication broker; accepts only the local sean UID."""
import json
import os
from pathlib import Path
import pwd
import socket
import struct

SOCKET = '/run/pi-station-auth/auth.sock'

def authenticate(password):
    """Authenticate through loopback SSH, pinned to this Pi's public host key."""
    import base64
    import paramiko
    fields = Path('/etc/ssh/ssh_host_ed25519_key.pub').read_text().split()
    if fields[0] != 'ssh-ed25519':
        return False
    key = paramiko.Ed25519Key(data=base64.b64decode(fields[1]))
    client = paramiko.SSHClient()
    client.get_host_keys().add('127.0.0.1', 'ssh-ed25519', key)
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        client.connect('127.0.0.1', port=22, username='sean', password=password,
                       allow_agent=False, look_for_keys=False, timeout=6,
                       auth_timeout=6, banner_timeout=6)
        return client.get_transport().is_authenticated()
    except (paramiko.SSHException, OSError):
        return False
    finally:
        client.close()


def main():
    uid = pwd.getpwnam('sean').pw_uid
    Path(SOCKET).unlink(missing_ok=True)
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(SOCKET)
        os.chmod(SOCKET, 0o660)
        server.listen(4)
        while True:
            connection, _ = server.accept()
            with connection:
                connection.settimeout(8)
                try:
                    _, peer_uid, _ = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                    if peer_uid != uid:
                        continue
                    data = bytearray()
                    while not data.endswith(b'\n') and len(data) <= 4096:
                        chunk = connection.recv(4097 - len(data))
                        if not chunk:
                            break
                        data.extend(chunk)
                    request = json.loads(data)
                    password = request.get('password')
                    allowed = isinstance(password, str) and 0 < len(password.encode()) <= 1024 and '\0' not in password
                    ok = allowed and request.get('username') == 'sean' and authenticate(password)
                    connection.sendall(json.dumps({'ok': bool(ok)}).encode() + b'\n')
                except (ValueError, OSError, TypeError):
                    pass

if __name__ == '__main__':
    main()

