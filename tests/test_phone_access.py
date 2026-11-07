"""Local phone listener acceptance; synthetic config and no TikTok requests."""
import ast
import contextlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import sys
import threading
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def server_class():
    tree = ast.parse((ROOT / 'main.py').read_text(encoding='utf-8'))
    nodes = [n for n in tree.body if isinstance(n, ast.ClassDef)
             and n.name == '_QuietThreadingHTTPServer']
    namespace = {'ThreadingHTTPServer': ThreadingHTTPServer, 'threading': threading,
                 'sys': sys, 'phone_addresses': lambda: ['127.0.0.2']}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'main.py', 'exec'), namespace)
    return namespace['_QuietThreadingHTTPServer']


def application_handler():
    tree = ast.parse((ROOT / 'main.py').read_text(encoding='utf-8'))
    handler = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Handler')
    names = ('_json', '_drain_body', '_secure_link', '_client_ip', '_auth_ok', '_auth_required',
             '_foreign', '_allowed', '_api_auth_get', '_api_auth_login', '_api_auth_logout',
             '_read_json', '_settings_payload', '_api_settings_put')
    methods = [n for n in handler.body if isinstance(n, ast.FunctionDef) and n.name in names]
    from modules import config
    import urllib.parse
    scope = {'json': json, 'config': config, 'urllib': __import__('urllib'), '_MAX_BODY': 1024 * 1024,
             'phone_links': lambda port: []}
    exec(compile(ast.Module(body=methods, type_ignores=[]), 'main.py', 'exec'), scope)
    def get(self):
        if not self._allowed(self.path): return
        if self.path == '/api/auth': self._api_auth_get()
        elif self.path == '/api/settings': self._json(self._settings_payload())
        else: self._json({'ok': True})
    def put(self):
        if self._allowed(self.path): self._api_settings_put()
    def post(self):
        if self._allowed(self.path): self._api_auth_login()
    return type('ApplicationHandler', (BaseHTTPRequestHandler,), {
        **{name: scope[name] for name in names}, 'do_GET': get, 'do_PUT': put, 'do_POST': post,
        'log_message': lambda *args: None})


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({'shared': 'same-handler'}).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class PhoneAccessTests(unittest.TestCase):
    def test_local_listener_does_not_wait_for_reverse_dns(self):
        with patch.object(socket, 'getfqdn', side_effect=AssertionError('No reverse DNS for a local listener')):
            server = server_class()(('127.0.0.1', 0), Handler)
        try:
            self.assertEqual(server.server_name, '127.0.0.1')
            self.assertGreater(server.server_port, 0)
        finally:
            server.server_close()

    def test_switch_opens_and_closes_lan_without_changing_local_listener(self):
        server = server_class()(('127.0.0.1', 0), Handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        port = server.server_address[1]
        server.set_phone_access(True)
        conn = http.client.HTTPConnection('127.0.0.2', port, timeout=2)
        conn.request('GET', '/')
        self.assertEqual(conn.getresponse().status, 200)
        conn.close()
        self.assertEqual(server.phone_status(), {'active': True, 'supported': True,
                                               'connected': True,
                                               'links': [f'http://127.0.0.2:{port}']})
        server.set_phone_access(False)
        with self.assertRaises(OSError):
            socket.create_connection(('127.0.0.2', port), timeout=.5)
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
        conn.request('GET', '/')
        self.assertEqual(conn.getresponse().status, 200)
        conn.close()

    def test_settings_switch_updates_listener_before_returning(self):
        from tests.test_settings_browser import BrowserSettingsTest
        fixture = BrowserSettingsTest()
        fixture.setUp()
        fixture.modules.auth.enabled = lambda: True
        fixture.config.get = lambda name, default=None: fixture.cfg.get(name, default)
        calls = []
        fixture.handler.server.set_phone_access = lambda enabled: calls.append(enabled)
        fixture.handler.server.phone_status = lambda: {'active': bool(calls and calls[-1]),
                                                       'supported': True, 'links': ['http://192.168.1.5:8740']}
        status, body = fixture.put({'phone_access': True})
        self.assertEqual(status, 200)
        self.assertEqual(calls, [True])
        self.assertTrue(body['phone']['active'])
        self.assertTrue(fixture.cfg['phone_access'])

    def test_listener_failure_does_not_save_enabled_setting(self):
        from tests.test_settings_browser import BrowserSettingsTest
        fixture = BrowserSettingsTest()
        fixture.setUp()
        fixture.modules.auth.enabled = lambda: True
        fixture.config.get = lambda name, default=None: fixture.cfg.get(name, default)
        fixture.handler.server.set_phone_access = lambda enabled: (_ for _ in ()).throw(OSError('occupied'))
        fixture.handler.server.phone_status = lambda: {'active': False}
        status, _ = fixture.put({'phone_access': True})
        self.assertEqual(status, 409)
        self.assertFalse(fixture.cfg.get('phone_access', False))

    def test_disk_failure_rolls_back_listener(self):
        from tests.test_settings_browser import BrowserSettingsTest
        fixture = BrowserSettingsTest()
        fixture.setUp()
        fixture.modules.auth.enabled = lambda: True
        fixture.config.get = lambda name, default=None: fixture.cfg.get(name, default)
        fixture.config.update = lambda body: (_ for _ in ()).throw(OSError('fixture full disk'))
        calls = []
        fixture.handler.server.set_phone_access = lambda enabled: calls.append(enabled)
        fixture.handler.server.phone_status = lambda: {'active': bool(calls and calls[-1])}
        status, _ = fixture.put({'phone_access': True})
        self.assertEqual(status, 500)
        self.assertEqual(calls, [True, False])

    def test_no_local_address_fails_without_listener(self):
        cls = server_class()
        cls.set_phone_access.__globals__['phone_addresses'] = lambda: []
        server = cls(('127.0.0.1', 0), Handler)
        try:
            with self.assertRaises(OSError): server.set_phone_access(True)
            self.assertFalse(server.phone_status()['active'])
        finally:
            server.server_close()

    def test_busy_lan_address_does_not_leave_partial_listener(self):
        cls = server_class()
        server = cls(('127.0.0.1', 0), Handler)
        port = server.server_address[1]
        occupied = socket.socket()
        occupied.bind(('127.0.0.3', port))
        occupied.listen()
        cls.set_phone_access.__globals__['phone_addresses'] = lambda: ['127.0.0.2', '127.0.0.3']
        try:
            with self.assertRaises(OSError): server.set_phone_access(True)
            self.assertFalse(server.phone_status()['active'])
            with self.assertRaises(OSError): socket.create_connection(('127.0.0.2', port), timeout=.5)
        finally:
            occupied.close()
            server.server_close()

    def test_lan_connection_is_observed_and_reset_on_disable(self):
        server = server_class()(('127.0.0.1', 0), Handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            server.set_phone_access(True)
            self.assertFalse(server.phone_status()['connected'])
            conn = http.client.HTTPConnection('127.0.0.2', server.server_address[1], timeout=2)
            conn.request('GET', '/')
            conn.getresponse().read()
            conn.close()
            self.assertTrue(server.phone_status()['connected'])
            server.set_phone_access(False)
            self.assertFalse(server.phone_status()['connected'])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_real_http_toggle_auth_and_cleanup(self):
        from modules import config, auth
        with tempfile.TemporaryDirectory() as tmp, patch.object(config, 'CONFIG_FILE', Path(tmp) / 'config.json'):
            config.write_text_atomic(config.CONFIG_FILE, '{}')
            auth.set_password('synthetic-phone-password')
            server = server_class()(('127.0.0.1', 0), application_handler())
            server.daemon_threads = True
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            port = server.server_address[1]
            def call(host, path, method='GET', body=None, cookie=None):
                conn = http.client.HTTPConnection(host, port, timeout=3)
                headers = {'Content-Type': 'application/json'}
                if cookie: headers['Cookie'] = cookie
                conn.request(method, path, json.dumps(body) if body is not None else None, headers)
                response = conn.getresponse()
                result = response.status, json.loads(response.read()), response.getheader('Set-Cookie')
                conn.close()
                return result
            try:
                status, settings, _ = call('127.0.0.1', '/api/settings', 'PUT', {'phone_access': True})
                self.assertEqual(status, 200)
                self.assertTrue(settings['phone']['active'])
                self.assertEqual(call('127.0.0.2', '/api/test')[0], 401)
                status, _, cookie = call('127.0.0.2', '/api/auth', 'POST', {'password': 'synthetic-phone-password'})
                self.assertEqual(status, 200)
                self.assertIsNotNone(cookie)
                self.assertEqual(call('127.0.0.2', '/api/test', cookie=cookie)[0], 200)
                self.assertFalse(call('127.0.0.1', '/api/settings')[1]['password']['required'])
                self.assertTrue(call('127.0.0.2', '/api/settings', cookie=cookie)[1]['password']['required'])
                self.assertEqual(call('127.0.0.1', '/api/settings', 'PUT', {'password': ''})[0], 400)
                status, settings, _ = call('127.0.0.2', '/api/settings', 'PUT', {'phone_access': False}, cookie=cookie)
                self.assertEqual(status, 200)
                self.assertFalse(settings['phone']['active'])
                with self.assertRaises(OSError): socket.create_connection(('127.0.0.2', port), timeout=.5)
                self.assertEqual(call('127.0.0.1', '/api/settings', 'PUT', {'phone_access': True})[0], 200)
                auth.clear_password()
                self.assertEqual(call('127.0.0.2', '/api/test', cookie=cookie)[0], 401)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(2)
            for address in ('127.0.0.1', '127.0.0.2'):
                with self.assertRaises(OSError): socket.create_connection((address, port), timeout=.5)


if __name__ == '__main__':
    unittest.main()
