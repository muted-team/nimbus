"""Локальная ручка настроек: без импорта сервера, сети и личного config.json."""
import ast
import copy
import threading
from pathlib import Path
import re
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

from modules import config
with patch.object(config, "get", side_effect=lambda name, default=None: default):
    from modules import client_device


def settings_handler(config, modules):
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    methods = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
               and node.name in ("_api_settings_put", "_commit_settings", "_settings_payload")]
    scope = {"config": config, "phone_links": lambda port: [], "_network_settings_lock": threading.RLock()}
    with patch.dict("sys.modules", {"modules": modules}):
        for method in methods:
            exec(compile(ast.Module(body=[method], type_ignores=[]), "main.py", "exec"), scope)
    return scope


class BrowserSettingsTest(unittest.TestCase):
    def setUp(self):
        self.cfg = {"browser_profile": "firefox155", "port": 8740, "host": "127.0.0.1"}
        self.config = SimpleNamespace(
            load=lambda: dict(self.cfg), update=self.update, THREADS_MAX=10, SERVER_WAIT_MAX=60,
            clamp_threads=lambda _: 2, clamp_server_wait=lambda _: 5,
        )
        self.modules = SimpleNamespace()
        self.modules.client_device = SimpleNamespace(
            BROWSER_PROFILES=client_device.BROWSER_PROFILES, browser_profile=lambda: "firefox155")
        self.modules.auth = SimpleNamespace(enabled=lambda: False, MIN_LEN=4)
        self.modules.proxy_pool = SimpleNamespace(on_death=lambda: "swap")
        self.modules.remote = SimpleNamespace(base=lambda: "", API_BASE="")
        self.methods = settings_handler(self.config, self.modules)
        self.handler = SimpleNamespace(server=SimpleNamespace(server_address=("127.0.0.1", 8740)))
        self.response: tuple[int, dict] | None = None
        self.handler._json = lambda body, status=200, **kwargs: setattr(self, "response", (status, body))
        self.handler._settings_payload = lambda cfg=None: self.methods["_settings_payload"](self.handler, cfg)
        self.handler._commit_settings = lambda body: self.methods["_commit_settings"](self.handler, body)

    def update(self, body):
        self.cfg.update(body)
        return dict(self.cfg)

    def put(self, body):
        self.handler._read_json = lambda: (body, None)
        with patch.dict("sys.modules", {"modules": self.modules}):
            self.methods["_api_settings_put"](self.handler)
        assert self.response is not None
        return self.response

    def test_selected_profile_is_saved_and_returned_with_active_profile(self):
        status, body = self.put({"browser_profile": "chrome152"})
        self.assertEqual(status, 200)
        self.assertEqual(self.cfg["browser_profile"], "chrome152")
        self.assertEqual(body["browser_profile"], "chrome152")
        self.assertEqual(body["browser_profile_active"], "firefox155")
        self.assertEqual(body["browser_profiles"], ["chrome152", "firefox155", "camoufox158"])

    def test_camoufox_is_saved_without_switching_the_running_profile(self):
        status, body = self.put({"browser_profile": "camoufox158"})
        self.assertEqual(status, 200)
        self.assertEqual(self.cfg["browser_profile"], "camoufox158")
        self.assertEqual(body["browser_profile"], "camoufox158")
        self.assertEqual(body["browser_profile_active"], "firefox155")

    def test_unknown_profile_does_not_write_other_settings(self):
        before = dict(self.cfg)
        status, _ = self.put({"browser_profile": "invalid", "port": 9999})
        self.assertEqual(status, 400)
        self.assertEqual(self.cfg, before)

    def test_password_changes_cannot_be_combined_with_any_other_setting(self):
        from unittest.mock import Mock
        self.modules.auth.set_password = Mock()
        self.modules.auth.clear_password = Mock()
        self.modules.auth.set_cookie_header = lambda secure: 'fixture-cookie'
        self.handler._secure_link = lambda: False
        self.config.get = lambda name, default=None: self.cfg.get(name, default)
        self.modules.remote.set_server = Mock(return_value='https://fixture.invalid')
        for other in ('port', 'threads', 'browser_profile', 'server', 'unknown_key'):
            with self.subTest(other=other):
                before = dict(self.cfg)
                status, body = self.put({'password': 'synthetic-password', other: 'fixture'})
                self.assertEqual(status, 400)
                self.assertIn('отдельно', body['error'])
                self.assertEqual(self.cfg, before)
        self.modules.auth.set_password.assert_not_called()
        self.modules.auth.clear_password.assert_not_called()
        self.modules.remote.set_server.assert_not_called()

    def test_network_bind_requires_a_saved_password_before_any_settings_write(self):
        before = dict(self.cfg)
        status, _ = self.put({"host": "0.0.0.0", "port": 9999})
        self.assertEqual(status, 400)
        self.assertEqual(self.cfg, before)

    def test_network_bind_is_saved_without_pretending_the_active_listener_changed(self):
        self.modules.auth.enabled = lambda: True
        status, body = self.put({"host": "0.0.0.0", "port": 9999})
        self.assertEqual(status, 200)
        self.assertEqual((body["host"], body["port"]), ("0.0.0.0", 9999))
        self.assertEqual(body["bound"], {"host": "127.0.0.1", "port": 8740})
        self.assertIs(self.cfg.get("bind_explicit"), True)
        self.assertIs(body.get("bind_explicit"), True)

    def test_payload_does_not_mistake_legacy_wildcard_default_for_an_explicit_bind(self):
        self.cfg["host"] = "0.0.0.0"
        with patch.dict("sys.modules", {"modules": self.modules}):
            body = self.handler._settings_payload()
        self.assertIs(body.get("bind_explicit"), False)

    def test_local_bind_can_be_saved_without_a_password(self):
        status, _ = self.put({"host": "127.0.0.1"})
        self.assertEqual(status, 200)

    def test_bind_accepts_only_canonical_ipv4_and_normalizes_loopback_aliases(self):
        self.modules.auth.enabled = lambda: True
        for host in ('0.0.0.0', '192.168.1.5', '127.0.0.1'):
            with self.subTest(host=host):
                status, body = self.put({'host': host})
                self.assertEqual(status, 200)
                self.assertEqual(body['host'], host)
        for host in ('localhost', '::1'):
            with self.subTest(host=host):
                status, body = self.put({'host': host})
                self.assertEqual(status, 200)
                self.assertEqual(body['host'], '127.0.0.1')

    def test_invalid_bind_shapes_do_not_persist_other_fields_or_remote_settings(self):
        from unittest.mock import Mock
        self.modules.auth.enabled = lambda: True
        self.modules.remote.set_server = Mock(return_value='https://fixture.invalid')
        for host in ('::', '2001:db8::1', '[::]', 'http://127.0.0.1', '192.168.1.5/path',
                     '192.168.001.5', '127.1', '2130706433', '0x7f000001', 'example.com'):
            with self.subTest(host=host):
                before = dict(self.cfg)
                status, _ = self.put({'host': host, 'port': 9999, 'server': 'https://fixture.invalid'})
                self.assertEqual(status, 400)
                self.assertEqual(self.cfg, before)
        self.modules.remote.set_server.assert_not_called()

    def test_phone_request_reports_the_primary_listener_as_the_active_bind(self):
        self.handler.server.server_address = ("192.168.1.5", 8740)
        self.handler.server.phone_parent = SimpleNamespace(server_address=("127.0.0.1", 8740))
        self.handler.server.phone_status = lambda: {"active": True, "supported": True, "links": ["http://192.168.1.5:8740"]}
        with patch.dict("sys.modules", {"modules": self.modules}):
            body = self.handler._settings_payload()
        self.assertEqual(body["bound"], {"host": "127.0.0.1", "port": 8740})
        self.assertEqual(body["phone"]["links"], ["http://192.168.1.5:8740"])

    def test_network_bound_primary_payload_reports_active_access_not_duplicate_phone_listeners(self):
        self.handler.server.server_address = ('0.0.0.0', 8740)
        self.handler.server.phone_status = lambda: {"active": False, "supported": True, "links": []}
        with patch.dict('sys.modules', {'modules': self.modules}):
            body = self.handler._settings_payload()
        self.assertTrue(body['phone']['active'])
        self.assertFalse(body['phone']['supported'])
        self.assertEqual(body['bound'], {'host': '0.0.0.0', 'port': 8740})

    def test_specific_network_bind_uses_its_actual_address_for_connection_links(self):
        self.handler.server.server_address = ('192.168.1.5', 8740)
        with patch.dict('sys.modules', {'modules': self.modules}):
            body = self.handler._settings_payload()
        self.assertEqual(body['phone']['links'], ['http://192.168.1.5:8740'])


    def test_http_profile_labels_offer_three_distinct_browser_choices(self):
        labels = (ROOT / "web/src/features/settings/labels.ts").read_text(encoding="utf-8")
        block = labels.split("export const BROWSER_LABEL", 1)[1].split("}", 1)[0]
        self.assertEqual(dict(re.findall(r'(\w+): "([^"]+)"', block)),
                         {"chrome152": "Chrome 152", "firefox155": "Firefox 155",
                          "camoufox158": "Camoufox 158"})
        types = (ROOT / "web/src/api/types.ts").read_text(encoding="utf-8")
        union = types.split("export type BrowserProfile =", 1)[1].split("\n", 1)[0]
        self.assertEqual(re.findall(r'"([^"]+)"', union),
                         ["chrome152", "firefox155", "camoufox158"])


    def test_password_removal_cannot_race_a_deferred_network_bind_commit(self):
        self.cfg.update(host='127.0.0.1', bind_explicit=True, phone_access=False)
        self.config.get = lambda name, default=None: self.cfg.get(name, default)
        password = {'set': True}
        self.modules.auth.enabled = lambda: password['set']
        self.modules.auth.clear_password = lambda: password.update(set=False)
        entered = threading.Event()
        release = threading.Event()
        remover_started = threading.Event()
        remover_finished = threading.Event()
        responses = {}
        errors = []
        def update(patch):
            if patch.get('host') == '0.0.0.0':
                entered.set()
                if not release.wait(2):
                    raise AssertionError('Test did not release network commit')
            return self.update(patch)
        self.config.update = update
        def request(name, body):
            handler = copy.copy(self.handler)
            handler._read_json = lambda: (body, None)
            handler._commit_settings = lambda body: self.methods['_commit_settings'](handler, body)
            handler._json = lambda payload, status=200, **kwargs: responses.update({name:(status,payload)})
            if name == 'remove': remover_started.set()
            try:
                self.methods['_api_settings_put'](handler)
            except BaseException as error:
                errors.append(error)
            finally:
                if name == 'remove': remover_finished.set()
        with patch.dict('sys.modules', {'modules': self.modules}):
            writer = threading.Thread(target=request, args=('host', {'host':'0.0.0.0'}))
            remover = threading.Thread(target=request, args=('remove', {'password':''}))
            writer.start()
            self.assertTrue(entered.wait(2))
            remover.start()
            try:
                self.assertTrue(remover_started.wait(2))
                self.assertFalse(remover_finished.wait(.1), 'Password removal ran inside an uncommitted host change')
            finally:
                release.set()
                writer.join(2)
                remover.join(2)
        self.assertEqual(errors, [])
        self.assertFalse(writer.is_alive() or remover.is_alive())
        self.assertEqual(responses['host'][0], 200)
        self.assertEqual(responses['remove'][0], 400)
        self.assertEqual(self.cfg['host'], '0.0.0.0')
        self.assertTrue(password['set'], 'Wildcard bind must never persist without a password')

    def test_unrelated_settings_are_not_blocked_by_the_network_password_lock(self):
        lock = self.methods['_api_settings_put'].__globals__['_network_settings_lock']
        finished = threading.Event()
        with patch.dict('sys.modules', {'modules': self.modules}), lock:
            worker = threading.Thread(target=lambda: (self.put({'browser_profile':'chrome152'}), finished.set()))
            worker.start()
            try:
                self.assertTrue(finished.wait(1))
            finally:
                worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.cfg['browser_profile'], 'chrome152')


if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()
