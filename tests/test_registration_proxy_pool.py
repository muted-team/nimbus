"""Synthetic registration proxy assignments; no checks or external requests."""
import contextlib
import unittest
from unittest.mock import patch

from modules import config, proxy_pool


A = "http://synthetic-a.invalid:8080"
B = "http://synthetic-b.invalid:8080"
C = "http://synthetic-c.invalid:8080"


class RegistrationProxyPoolTests(unittest.TestCase):
    def setUp(self):
        self.cfg = {"proxy_enabled": True, "proxies": [A, B, C], "proxies_login": [A],
                    "proxies_publish": [B, C], "proxies_registration": [A, B], "proxies_off": []}
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(config, "get", side_effect=lambda key, default=None: self.cfg.get(key, default)))
        self.stack.enter_context(patch.object(config, "load", side_effect=lambda: dict(self.cfg)))
        self.stack.enter_context(patch.object(proxy_pool, "_health", {}))
        self.stack.enter_context(patch.object(proxy_pool, "_leases", {}))
        self.stack.enter_context(patch.object(proxy_pool, "_pulse"))
        self.stack.enter_context(patch.object(proxy_pool, "_ensure_auto_check"))

    def test_existing_configs_do_not_inherit_login_or_publish_for_registration(self):
        del self.cfg["proxies_registration"]
        self.assertEqual(config.DEFAULTS["proxies_registration"], [])
        with self.assertRaises(proxy_pool.ProxySelectionError):
            proxy_pool.lease(recheck=False, task="registration")
        self.assertEqual(proxy_pool.configured("login"), [A])
        self.assertEqual(proxy_pool.configured("publish"), [B, C])

    def test_registration_uses_global_least_busy_leases_with_ordered_ties(self):
        held = []
        try:
            login = proxy_pool.lease(recheck=False, task="login")
            held.append(login)
            registration = proxy_pool.lease(recheck=False, task="registration")
            held.append(registration)
            publication = proxy_pool.lease(recheck=False, task="publish")
            held.append(publication)
            tie = proxy_pool.lease(recheck=False, task="registration")
            held.append(tie)
            self.assertEqual([item.url for item in held], [A, B, C, A])
            self.assertEqual(registration.task, "registration")
            self.assertEqual(proxy_pool._leases, {A: 2, B: 1, C: 1})
        finally:
            for item in held:
                item.release()
                item.release()
        self.assertEqual(proxy_pool._leases, {})

    def test_disabled_rows_cannot_be_leased_for_registration(self):
        self.cfg["proxies_off"] = [A]
        self.assertEqual(proxy_pool.configured("registration"), [B])
        self.cfg["proxies_off"] = [A, B]
        with self.assertRaises(proxy_pool.ProxySelectionError):
            proxy_pool.lease(recheck=False, task="registration")

    def test_health_snapshot_reports_independent_registration_marks(self):
        self.cfg["proxies_registration"] = [B]
        rows = proxy_pool.snapshot([A, B, C])
        self.assertEqual([row["registration"] for row in rows], [False, True, False])
        self.assertEqual([row["login"] for row in rows], [True, False, False])
        self.assertEqual([row["publish"] for row in rows], [False, True, True])

    def test_detected_proxy_scheme_preserves_registration_assignment(self):
        with patch.object(config, "update", return_value=self.cfg) as update:
            rewritten = proxy_pool._apply_detected_scheme(A, "socks5")
        self.assertEqual(rewritten, "socks5://synthetic-a.invalid:8080")
        self.assertEqual(update.call_args.args[0]["proxies_registration"], [rewritten, B])
        self.assertEqual(update.call_args.args[0]["proxies_login"], [rewritten])
        self.assertNotIn("proxies_publish", update.call_args.args[0])

    def test_proxy_assignment_api_updates_only_explicit_registration_indexes(self):
        import main
        handler = main.Handler.__new__(main.Handler)
        handler._read_json = lambda: ({"registration": [1, True, -1, 99, "0", 0]}, None)
        handler._campaign_running = lambda: False
        handler._proxies_payload = lambda cfg: {"ok": True}
        replies = []
        handler._json = lambda payload, *args: replies.append(payload)
        with patch.object(config, "update", return_value=self.cfg) as update:
            handler._api_proxies_put()
        self.assertEqual(update.call_args.args[0], {"proxies_registration": [B, A]})
        self.assertEqual(replies, [{"ok": True, "errors": []}])
