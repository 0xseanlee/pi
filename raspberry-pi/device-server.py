#!/usr/bin/env python3
"""Local TLS dashboard, PAM-backed login and server-side sessions."""
import argparse
from collections import defaultdict, deque
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import secrets
import socket
import ssl
import threading
import time
from urllib.parse import urlsplit

ALLOWED_ORIGINS = {'https://0xseanlee.me', 'https://0xseanlee.github.io',
                   'http://localhost:8080', 'http://127.0.0.1:8080'}
ASSETS = {'/': ('index.html', 'text/html; charset=utf-8'),
          '/index.html': ('index.html', 'text/html; charset=utf-8'),
          '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
          '/style.css': ('style.css', 'text/css; charset=utf-8')}
COOKIE = '__Host-pi-session'
IDLE_SECONDS = 1800
MAX_SECONDS = 28800


def local_host(host):
    if host in ('sean.local', 'sean', 'localhost'):
        return True
    try:
        address = ipaddress.ip_address(host)
        return address.version == 4 and (address.is_private or address.is_loopback) and not address.is_unspecified
    except ValueError:
        return False


def pam_login(username, password):
    try:
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(15)
            client.connect('/run/pi-station-auth/auth.sock')
            client.sendall(json.dumps({'username': username, 'password': password}).encode() + b'\n')
            return json.loads(client.recv(128)).get('ok') is True
    except (OSError, ValueError):
        return False


class Auth:
    def __init__(self, verify=pam_login, clock=time.monotonic):
        self.verify, self.clock = verify, clock
        self.sessions = {}
        self.attempts = defaultdict(deque)
        self.global_attempts = deque()
        self.lock = threading.Lock()
        self.login_slot = threading.BoundedSemaphore(1)

    def cleanup(self, now):
        self.sessions = {key: value for key, value in self.sessions.items()
                         if now - value['seen'] < IDLE_SECONDS and now - value['created'] < MAX_SECONDS}
        for key in list(self.attempts):
            while self.attempts[key] and now - self.attempts[key][0] >= 60:
                self.attempts[key].popleft()
            if not self.attempts[key]:
                del self.attempts[key]
        while self.global_attempts and now - self.global_attempts[0] >= 60:
            self.global_attempts.popleft()

    def login(self, address, username, password, previous=''):
        with self.lock:
            now = self.clock()
            self.cleanup(now)
            if len(self.attempts[address]) >= 5 or len(self.global_attempts) >= 20:
                return 429, None
            if not self.login_slot.acquire(blocking=False):
                return 429, None
            self.attempts[address].append(now)
            self.global_attempts.append(now)
        try:
            ok = username == 'sean' and self.verify(username, password)
        finally:
            self.login_slot.release()
        if not ok:
            return 401, None
        with self.lock:
            self.sessions.pop(previous, None)
            if len(self.sessions) >= 32:
                oldest = min(self.sessions, key=lambda key: self.sessions[key]['created'])
                del self.sessions[oldest]
            token = secrets.token_urlsafe(32)
            self.sessions[token] = {'csrf': secrets.token_urlsafe(32), 'created': now, 'seen': now}
            return 200, (token, self.sessions[token]['csrf'])

    def session(self, token, touch=False):
        with self.lock:
            now = self.clock()
            self.cleanup(now)
            value = self.sessions.get(token)
            if value and touch:
                value['seen'] = now
            return dict(value) if value else None

    def logout(self, token):
        with self.lock:
            self.sessions.pop(token, None)


class Handler(BaseHTTPRequestHandler):
    server_version = 'PiStation/0.3'

    def setup(self):
        self.request.settimeout(10)
        try:
            if self.server.secure:
                self.request = self.server.context.wrap_socket(self.request, server_side=True)
            super().setup()
        except Exception:
            self.request.close()
            raise

    def finish(self):
        try:
            super().finish()
        finally:
            self.connection.close()

    def reply(self, status, data=None, content_type='application/json', head=False, headers=None):
        body = data if isinstance(data, bytes) else json.dumps(data or {}).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if self.path.split('?')[0] == '/api/v1/discovery':
            self.send_header('Vary', 'Origin')
            origin = self.headers.get('Origin')
            if origin in ALLOWED_ORIGINS:
                self.send_header('Access-Control-Allow-Origin', origin)
                self.send_header('Access-Control-Allow-Methods', 'GET, HEAD, OPTIONS')
                self.send_header('Access-Control-Allow-Private-Network', 'true')
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def own_origin(self):
        scheme = 'https' if self.server.secure else 'http'
        return f"{scheme}://{self.headers.get('Host', '')}"

    def safe_host(self):
        try:
            url = urlsplit(self.own_origin())
            return url.hostname if local_host(url.hostname) and url.port == self.server.server_port else None
        except (ValueError, TypeError):
            return None

    def token(self):
        try:
            cookies = SimpleCookie(self.headers.get('Cookie', ''))
            return cookies[COOKIE].value if COOKIE in cookies else ''
        except CookieError:
            return ''

    def authorized_origin(self, mutation=False):
        origin = self.headers.get('Origin')
        return origin == self.own_origin() if mutation else not origin or origin == self.own_origin()

    def do_OPTIONS(self):
        if not self.safe_host() or self.path != '/api/v1/discovery' or self.headers.get('Origin') not in ALLOWED_ORIGINS:
            self.reply(403, {'error': 'origin_not_allowed'})
        else:
            self.reply(204)

    def do_GET(self, head=False):
        host = self.safe_host()
        if not host:
            self.reply(403, {'error': 'host_not_allowed'}, head=head)
            return
        path = urlsplit(self.path).path
        if path == '/api/v1/discovery':
            origin = self.headers.get('Origin')
            if origin and origin not in ALLOWED_ORIGINS and origin != self.own_origin():
                self.reply(403, {'error': 'origin_not_allowed'}, head=head)
            else:
                self.reply(200, {'service': 'pi-station', 'api_version': 1,
                                 'device_id': 'sean', 'login_required': True, 'tls_port': self.server.tls_port}, head=head)
            return
        if not self.server.secure:
            if path in ASSETS:
                self.reply(302, headers={'Location': f'https://{host}:{self.server.tls_port}/'}, head=head)
            else:
                self.reply(403, {'error': 'https_required'}, head=head)
            return
        if not self.authorized_origin():
            self.reply(403, {'error': 'origin_not_allowed'}, head=head)
            return
        if path in ASSETS:
            name, content_type = ASSETS[path]
            try:
                self.reply(200, (self.server.web_root / name).read_bytes(), content_type, head)
            except OSError:
                self.reply(503, {'error': 'dashboard_unavailable'}, head=head)
            return
        session = self.server.auth.session(self.token())
        if path == '/api/v1/session':
            self.reply(200, {'authenticated': bool(session), **({'username': 'sean', 'csrf': session['csrf']} if session else {})}, head=head)
        elif path.startswith('/api/v1/') and not session:
            self.reply(401, {'error': 'login_required'}, head=head)
        elif path == '/api/v1/identity':
            self.reply(200, {'service': 'pi-station', 'api_version': 1, 'hostname': socket.gethostname(),
                             'capabilities': ['discovery', 'login']}, head=head)
        else:
            self.reply(404, {'error': 'not_found'}, head=head)

    def do_HEAD(self):
        self.do_GET(head=True)

    def do_POST(self):
        if not self.server.secure:
            self.reply(403, {'error': 'https_required'})
            return
        if not self.safe_host() or not self.authorized_origin(mutation=True):
            self.reply(403, {'error': 'origin_not_allowed'})
            return
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json' or self.headers.get('Transfer-Encoding'):
            self.reply(415, {'error': 'json_required'})
            return
        try:
            size = int(self.headers.get('Content-Length', '-1'))
            if not 0 <= size <= 4096:
                raise ValueError()
            request = json.loads(self.rfile.read(size))
            if not isinstance(request, dict):
                raise ValueError()
        except (ValueError, OSError):
            self.reply(400, {'error': 'invalid_request'})
            return
        path = urlsplit(self.path).path
        if path == '/api/v1/login':
            username, password = request.get('username'), request.get('password')
            if not isinstance(username, str) or not isinstance(password, str) or not 0 < len(password.encode()) <= 1024 or '\0' in password:
                self.reply(400, {'error': 'invalid_request'})
                return
            code, result = self.server.auth.login(self.client_address[0], username, password, self.token())
            if code != 200:
                self.reply(code, {'error': 'too_many_attempts' if code == 429 else 'invalid_credentials'}, headers={'Retry-After': '60'} if code == 429 else None)
                return
            token, csrf = result
            self.reply(200, {'authenticated': True, 'username': 'sean', 'csrf': csrf}, headers={
                'Set-Cookie': f'{COOKIE}={token}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age={MAX_SECONDS}'})
            return
        session = self.server.auth.session(self.token())
        if not session:
            self.reply(401, {'error': 'login_required'})
        elif not secrets.compare_digest(self.headers.get('X-CSRF-Token', ''), session['csrf']):
            self.reply(403, {'error': 'csrf_required'})
        elif path == '/api/v1/logout':
            self.server.auth.logout(self.token())
            self.reply(200, {'authenticated': False}, headers={'Set-Cookie': f'{COOKIE}=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0'})
        else:
            self.reply(404, {'error': 'not_found'})

    def log_message(self, format, *args):
        # Request lines can contain untrusted queries. Never log request bodies or cookies.
        return


class Server(ThreadingHTTPServer):
    def __init__(self, *args):
        self.slots = threading.BoundedSemaphore(32)
        super().__init__(*args)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


def make_server(host, port, web_root, auth, secure, tls_port):
    server = Server((host, port), Handler)
    server.web_root, server.auth, server.secure, server.tls_port = web_root.resolve(), auth, secure, tls_port
    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--tls-port', type=int, default=8443)
    parser.add_argument('--web-root', type=Path, default=Path('/opt/pi-station/web'))
    parser.add_argument('--cert', type=Path, required=True)
    parser.add_argument('--key', type=Path, required=True)
    args = parser.parse_args()
    auth = Auth()
    plain = make_server(args.host, args.port, args.web_root, auth, False, args.tls_port)
    secure = make_server(args.host, args.tls_port, args.web_root, auth, True, args.tls_port)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(args.cert, args.key)
    secure.context = context
    threading.Thread(target=plain.serve_forever, daemon=True).start()
    secure.serve_forever()

if __name__ == '__main__':
    main()
