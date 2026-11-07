"""Локальная ручка настроек: без импорта сервера, сети и личного config.json."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def settings_handler(config, modules):
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    methods = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
               and node.name in ("_api_settings_put", "_settings_payload")]
    scope = {"config": config, "phone_links": lambda port: []}
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
            BROWSER_PROFILES=("chrome152", "firefox155"), browser_profile=lambda: "firefox155")
        self.modules.auth = SimpleNamespace(enabled=lambda: False, MIN_LEN=4)
        self.modules.proxy_pool = SimpleNamespace(on_death=lambda: "swap")
        self.modules.remote = SimpleNamespace(base=lambda: "", API_BASE="")
        self.methods = settings_handler(self.config, self.modules)
        self.handler = SimpleNamespace(server=SimpleNamespace(server_address=("127.0.0.1", 8740)))
        self.response: tuple[int, dict] | None = None
        self.handler._json = lambda body, status=200, **kwargs: setattr(self, "response", (status, body))
        self.handler._settings_payload = lambda cfg=None: self.methods["_settings_payload"](self.handler, cfg)

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
        self.assertEqual(body["browser_profiles"], ["chrome152", "firefox155"])

    def test_unknown_profile_does_not_write_other_settings(self):
        before = dict(self.cfg)
        status, _ = self.put({"browser_profile": "invalid", "port": 9999})
        self.assertEqual(status, 400)
        self.assertEqual(self.cfg, before)


if __name__ == "__main__":
    unittest.main()
