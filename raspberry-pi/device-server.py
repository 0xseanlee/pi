#!/usr/bin/env python3
"""Read-only Pi Station identity endpoint and local dashboard; no command API."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
from urllib.parse import urlsplit

ALLOWED_ORIGINS = {'https://0xseanlee.me', 'https://0xseanlee.github.io',
                   'http://localhost:8080', 'http://127.0.0.1:8080'}
ASSETS = {'/': ('index.html', 'text/html; charset=utf-8'),
          '/index.html': ('index.html', 'text/html; charset=utf-8'),
          '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
          '/style.css': ('style.css', 'text/css; charset=utf-8')}


class Handler(BaseHTTPRequestHandler):
    server_version = 'PiStation/0.2'

    def reply(self, status, body=b'', content_type='application/json', head=False):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Vary', 'Origin')
        origin = self.headers.get('Origin')
        if origin in ALLOWED_ORIGINS:
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Access-Control-Allow-Methods', 'GET, HEAD, OPTIONS')
            self.send_header('Access-Control-Allow-Private-Network', 'true')
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def origin_allowed(self):
        origin = self.headers.get('Origin')
        host = self.headers.get('Host', '')
        return not origin or origin in ALLOWED_ORIGINS or origin == 'http://' + host

    def do_OPTIONS(self):
        if not self.origin_allowed():
            self.reply(403)
            return
        self.reply(204)

    def do_GET(self, head=False):
        if not self.origin_allowed():
            self.reply(403, b'{"error":"origin_not_allowed"}', head=head)
            return
        path = urlsplit(self.path).path
        if path == '/api/v1/identity':
            body = json.dumps({'service': 'pi-station', 'api_version': 1,
                               'hostname': socket.gethostname(),
                               'capabilities': ['discovery']}).encode()
            self.reply(200, body, head=head)
        elif path in ASSETS:
            name, content_type = ASSETS[path]
            try:
                self.reply(200, (self.server.web_root / name).read_bytes(), content_type, head)
            except OSError:
                self.reply(503, b'{"error":"dashboard_unavailable"}', head=head)
        else:
            self.reply(404, b'{"error":"not_found"}', head=head)

    def do_HEAD(self):
        self.do_GET(head=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--web-root', type=Path, default=Path('/opt/pi-station/web'))
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.web_root = args.web_root.resolve()
    server.serve_forever()


if __name__ == '__main__':
    main()
