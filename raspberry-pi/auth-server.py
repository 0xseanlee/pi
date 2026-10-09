#!/usr/bin/env python3
"""Root-only PAM broker. Accepts requests only from the local sean UID."""
import ctypes as C
import ctypes.util
import json
import os
from pathlib import Path
import pwd
import socket
import struct

SOCKET = '/run/pi-station-auth/auth.sock'

class Message(C.Structure):
    _fields_ = [('style', C.c_int), ('message', C.c_char_p)]

class Response(C.Structure):
    _fields_ = [('response', C.c_void_p), ('code', C.c_int)]

CALLBACK = C.CFUNCTYPE(C.c_int, C.c_int, C.POINTER(C.POINTER(Message)),
                       C.POINTER(C.POINTER(Response)), C.c_void_p)

class Conversation(C.Structure):
    _fields_ = [('callback', CALLBACK), ('data', C.c_void_p)]


def authenticate(password):
    pam = C.CDLL(ctypes.util.find_library('pam'))
    libc = C.CDLL(ctypes.util.find_library('c'))
    libc.calloc.argtypes = [C.c_size_t, C.c_size_t]
    libc.calloc.restype = C.c_void_p
    libc.strdup.argtypes = [C.c_char_p]
    libc.strdup.restype = C.c_void_p
    libc.free.argtypes = [C.c_void_p]
    pam.pam_start.argtypes = [C.c_char_p, C.c_char_p, C.POINTER(Conversation), C.POINTER(C.c_void_p)]
    pam.pam_authenticate.argtypes = [C.c_void_p, C.c_int]
    pam.pam_acct_mgmt.argtypes = [C.c_void_p, C.c_int]
    pam.pam_end.argtypes = [C.c_void_p, C.c_int]

    @CALLBACK
    def converse(count, messages, output, _):
        if not 1 <= count <= 32:
            return 19
        raw = libc.calloc(count, C.sizeof(Response))
        if not raw:
            return 19
        replies = C.cast(raw, C.POINTER(Response))
        for i in range(count):
            style = messages[i].contents.style
            if style in (1, 2):
                value = password.encode() if style == 1 else b'sean'
                replies[i].response = libc.strdup(value)
                if not replies[i].response:
                    for j in range(i):
                        if replies[j].response:
                            libc.free(replies[j].response)
                    libc.free(raw)
                    return 19
            elif style not in (3, 4):
                for j in range(i):
                    if replies[j].response:
                        libc.free(replies[j].response)
                libc.free(raw)
                return 19
        output[0] = replies
        return 0

    handle = C.c_void_p()
    conversation = Conversation(converse, None)
    code = pam.pam_start(b'pi-station', b'sean', C.byref(conversation), C.byref(handle))
    if code:
        return False
    try:
        code = pam.pam_authenticate(handle, 0)
        if code == 0:
            code = pam.pam_acct_mgmt(handle, 0)
        return code == 0
    finally:
        pam.pam_end(handle, code)


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
