"""Security boundaries verified over a real TLS socket with test-only credentials."""
import http.client
import importlib.util
import json
from pathlib import Path
import ssl
import subprocess
import tempfile
import threading
import unittest

spec = importlib.util.spec_from_file_location('device', Path(__file__).parents[1] / 'raspberry-pi/device-server.py')
device = importlib.util.module_from_spec(spec)
spec.loader.exec_module(device)


class AuthStateTests(unittest.TestCase):
    def test_expiry_rotation_and_rate_limits(self):
        now = [100.0]
        auth = device.Auth(verify=lambda u, p: p == 'test-only', clock=lambda: now[0])
        code, (old, _) = auth.login('a', 'sean', 'test-only')
        self.assertEqual(code, 200)
        _, (new, _) = auth.login('a', 'sean', 'test-only', old)
        self.assertIsNone(auth.session(old))
        self.assertIsNotNone(auth.session(new))
        now[0] += device.IDLE_SECONDS
        self.assertIsNone(auth.session(new))
        for _ in range(5):
            self.assertEqual(auth.login('b', 'sean', 'wrong')[0], 401)
        self.assertEqual(auth.login('b', 'sean', 'test-only')[0], 429)
        now[0] += 60
        self.assertEqual(auth.login('b', 'sean', 'test-only')[0], 200)

    def test_other_username_never_reaches_pam(self):
        auth = device.Auth(verify=lambda *_: self.fail('unexpected authentication'))
        self.assertEqual(auth.login('a', 'root', 'test-only')[0], 401)


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        (cls.root / 'index.html').write_text('test dashboard')
        cert, key = cls.root / 'cert.pem', cls.root / 'key.pem'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                        '-subj', '/CN=127.0.0.1', '-addext', 'subjectAltName=IP:127.0.0.1',
                        '-keyout', str(key), '-out', str(cert)], check=True, capture_output=True)
        cls.context = ssl.create_default_context(cafile=str(cert))
        cls.tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        cls.tls.minimum_version = ssl.TLSVersion.TLSv1_2
        cls.tls.load_cert_chain(cert, key)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.auth = device.Auth(verify=lambda u, p: p == 'test-only')
        self.secure = device.make_server('127.0.0.1', 0, self.root, self.auth, True, 8443)
        self.secure.context = self.tls
        self.plain = device.make_server('127.0.0.1', 0, self.root, self.auth, False, self.secure.server_port)
        self.origin = f'https://127.0.0.1:{self.secure.server_port}'
        for server in (self.secure, self.plain):
            threading.Thread(target=server.serve_forever, daemon=True).start()

    def tearDown(self):
        for server in (self.secure, self.plain):
            server.shutdown()
            server.server_close()

    def request(self, path, method='GET', data=None, headers=None, plain=False):
        server = self.plain if plain else self.secure
        connection = http.client.HTTPConnection('127.0.0.1', server.server_port) if plain else http.client.HTTPSConnection('127.0.0.1', server.server_port, context=self.context)
        body = json.dumps(data) if data is not None else None
        merged = {'Origin': self.origin, 'Content-Type': 'application/json', **(headers or {})}
        connection.request(method, path, body=body, headers=merged)
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def login(self):
        code, headers, body = self.request('/api/v1/login', 'POST', {'username': 'sean', 'password': 'test-only'})
        self.assertEqual(code, 200)
        return headers['Set-Cookie'].split(';')[0], json.loads(body)['csrf'], headers['Set-Cookie']

    def test_locked_identity_discovery_and_static_allowlist(self):
        self.assertEqual(self.request('/api/v1/identity')[0], 401)
        self.assertEqual(self.request('/api/v1/anything')[0], 401)
        self.assertEqual(json.loads(self.request('/api/v1/session')[2]), {'authenticated': False})
        discovery = json.loads(self.request('/api/v1/discovery')[2])
        self.assertTrue(discovery['login_required'])
        self.assertNotIn('hostname', discovery)
        self.assertEqual(self.request('/')[0], 200)
        self.assertEqual(self.request('/../../etc/shadow')[0], 404)

    def test_https_required_host_and_origin_boundaries(self):
        self.assertEqual(self.request('/api/v1/login', 'POST', {'username': 'sean', 'password': 'test-only'}, plain=True)[0], 403)
        self.assertEqual(self.request('/', plain=True)[1]['Location'], self.origin + '/')
        self.assertEqual(self.request('/api/v1/session', headers={'Host': 'attacker.example'})[0], 403)
        for origin in ('https://attacker.example', 'null', 'https://0xseanlee.me', ''):
            self.assertEqual(self.request('/api/v1/login', 'POST', {'username': 'sean', 'password': 'test-only'}, headers={'Origin': origin})[0], 403)
        self.assertEqual(self.request('/api/v1/login', 'POST', {}, headers={'Content-Type': 'text/plain'})[0], 415)

    def test_login_cookie_csrf_logout_and_no_cached_auth(self):
        self.assertEqual(self.request('/api/v1/login', 'POST', {'username': 'sean', 'password': 'wrong'})[0], 401)
        cookie, csrf, flags = self.login()
        for flag in ('HttpOnly', 'Secure', 'SameSite=Strict', 'Path=/'):
            self.assertIn(flag, flags)
        self.assertTrue(cookie.startswith('__Host-pi-session='))
        code, headers, body = self.request('/api/v1/identity', headers={'Cookie': cookie})
        self.assertEqual(code, 200)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertNotIn('password', body.decode())
        self.assertEqual(self.request('/api/v1/logout', 'POST', {}, headers={'Cookie': cookie})[0], 403)
        self.assertEqual(self.request('/api/v1/logout', 'POST', {}, headers={'Cookie': cookie, 'X-CSRF-Token': csrf})[0], 200)
        self.assertEqual(self.request('/api/v1/identity', headers={'Cookie': cookie})[0], 401)

    def test_failed_login_throttled(self):
        for _ in range(5):
            self.assertEqual(self.request('/api/v1/login', 'POST', {'username': 'sean', 'password': 'wrong'})[0], 401)
        code, headers, _ = self.request('/api/v1/login', 'POST', {'username': 'sean', 'password': 'test-only'})
        self.assertEqual(code, 429)
        self.assertEqual(headers['Retry-After'], '60')

if __name__ == '__main__':
    unittest.main()
