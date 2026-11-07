# -*- coding: utf-8 -*-
"""Account-proxy negotiation regressions; synthetic transport only.

Run this standalone unittest script from an isolated source-only copy.
No server, account files, proxy checks or actual HTTP requests are used.
"""
import contextlib
import sys
import threading
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import call, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules import config  # noqa: E402

# Import-time browser defaults must not read a user's configuration.
with patch.object(config, "get", side_effect=lambda name, default=None: default):
    from modules import client_device, proxy_pool, remote  # noqa: E402

BASE = "https://remote-profile.invalid"
PROXY = "socks5://fixture:synthetic@account-proxy.invalid:1080"
ROUTE = "socks5h://fixture:synthetic@account-proxy.invalid:1080"
PROFILE = "firefox155"
TOKEN = "synthetic-license-key"
ACTION = "/v1/synthetic-action"
RESULT = {"ok": True, "synthetic": True}


class _ConnectError(Exception):
    code = 7  # Definitely unsent: direct connection could not be opened.


class _CurlError(Exception):
    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


class _Response:
    def __init__(self, status, headers):
        self.status_code = status
        self.headers = headers

    def json(self):
        return dict(RESULT)


class _Session:
    def __init__(self, owner):
        self.owner = owner
        self.proxies = {}

    def request(self, method, url, **kwargs):
        return self.owner.transport(self.proxies.get("all", ""), method, url, kwargs)


class RemoteProfileProxyTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.direct_blocked = True
        self.health_status = 200
        self.health_profile = PROFILE
        self.health_error = None
        patches = [
            patch.object(config, "get", side_effect=lambda name, default=None: default),
            patch.object(config, "server_wait_min", return_value=1),
            patch.object(remote, "base", return_value=BASE),
            patch.object(remote, "_local", threading.local()),
            patch.object(remote, "_profile_negotiated", {}),
            patch.object(remote, "_direct_off_until", 0.0),
            patch.object(proxy_pool, "_alive_now", return_value=([], [])),
            patch.object(remote.requests, "Session", side_effect=lambda: _Session(self)),
        ]
        for context in patches:
            context.start()
            self.addCleanup(context.stop)

    def transport(self, route, method, url, kwargs):
        self.calls.append((route, method, url, kwargs))
        if not route and self.direct_blocked:
            raise _ConnectError("synthetic direct connection refused")
        if url == BASE + "/v2/health":
            if self.health_error is not None:
                raise self.health_error
            headers = ({"X-TikTok-Browser-Profile": self.health_profile}
                       if self.health_profile is not None else {})
            return _Response(self.health_status, headers)
        return _Response(200, {"X-TikTok-Browser-Profile":
                               kwargs["headers"]["X-TikTok-Browser-Profile"]})

    def test_firefox_negotiation_uses_account_proxy_outside_pool(self):
        payload = {"username": "synthetic.user", "proxy": PROXY}
        with client_device.use_browser_profile(PROFILE):
            try:
                result = remote.request("POST", ACTION, json=payload, api_key=TOKEN)
            except remote.RemoteError as exc:
                self.fail(f"Account proxy must reach health before the action: {exc}; "
                          f"routes={[call[0] for call in self.calls]}")
        self.assertEqual(result, RESULT)
        self.assertEqual(
            [(route, method, url) for route, method, url, _ in self.calls],
            [("", "GET", BASE + "/v2/health"),
             (ROUTE, "GET", BASE + "/v2/health"),
             (ROUTE, "POST", BASE + "/v2/synthetic-action")],
        )
        for route, _, _, kwargs in self.calls:
            self.assertIs(kwargs["verify"], True)
            self.assertEqual(kwargs["headers"]["Authorization"], "Bearer " + TOKEN)
            self.assertEqual(kwargs["headers"]["X-TikTok-Browser-Profile"], PROFILE)
            if route:
                self.assertEqual(kwargs["timeout"], (proxy_pool.CONNECT_TIMEOUT, remote.TIMEOUT[1]))
        self.assertIs(self.calls[-1][3]["json"], payload)

    def test_chrome_keeps_v1_action_without_negotiation(self):
        payload = {"proxy": PROXY}
        with client_device.use_browser_profile("chrome152"):
            result = remote.request("POST", ACTION, json=payload, api_key=TOKEN)
        self.assertEqual(result, RESULT)
        self.assertEqual(
            [(route, method, url) for route, method, url, _ in self.calls],
            [("", "POST", BASE + ACTION), (ROUTE, "POST", BASE + ACTION)],
        )
        self.assertEqual(self.calls[-1][3]["headers"]["X-TikTok-Browser-Profile"], "chrome152")
        self.assertIs(self.calls[-1][3]["json"], payload)
        self.assertEqual(remote._profile_negotiated, {})

    def test_firefox_non_string_proxy_is_ignored_by_both_requests(self):
        self.direct_blocked = False
        for proxy in (None, 42, True, {"url": PROXY}, [PROXY]):
            with self.subTest(proxy=proxy):
                self.calls.clear()
                remote._profile_negotiated.clear()
                remote._direct_off_until = float("inf")
                payload = {"proxy": proxy}
                with client_device.use_browser_profile(PROFILE):
                    result = remote.request("POST", ACTION, json=payload, api_key=TOKEN)
                self.assertEqual(result, RESULT)
                self.assertEqual(
                    [(route, method, url) for route, method, url, _ in self.calls],
                    [("", "GET", BASE + "/v2/health"),
                     ("", "POST", BASE + "/v2/synthetic-action")],
                )
                self.assertIs(self.calls[-1][3]["json"], payload)

    def test_firefox_invalid_proxy_string_is_ignored_by_both_requests(self):
        self.direct_blocked = False
        invalid_proxies = (
            " \t",
            "socks5://",
            "socks5://account-proxy.invalid:not-a-port",
            "socks5://account-proxy.invalid:0",
            "socks5://account-proxy.invalid:65536",
            "ftp://account-proxy.invalid:1080",
            "socks5://[not-an-ipv6]:1080",
            "socks5://account proxy.invalid:1080",
            "\x00socks5://account-proxy.invalid:1080",
            "socks5://account-proxy.invalid:1080/extra",
            "socks5://account-proxy.invalid:1080?route=synthetic",
            "socks5://account-proxy.invalid:1080#fragment",
        )
        for proxy in invalid_proxies:
            with self.subTest(proxy=proxy):
                self.calls.clear()
                remote._profile_negotiated.clear()
                remote._direct_off_until = float("inf")
                payload = {"proxy": proxy}
                with client_device.use_browser_profile(PROFILE):
                    result = remote.request("POST", ACTION, json=payload, api_key=TOKEN)
                self.assertEqual(result, RESULT)
                self.assertEqual(
                    [(route, method, url) for route, method, url, _ in self.calls],
                    [("", "GET", BASE + "/v2/health"),
                     ("", "POST", BASE + "/v2/synthetic-action")],
                )
                self.assertIs(self.calls[-1][3]["json"], payload)

    def test_firefox_missing_proxy_still_negotiates(self):
        self.direct_blocked = False
        for payload in (None, {}, [{"proxy": PROXY}]):
            with self.subTest(payload=payload):
                self.calls.clear()
                remote._profile_negotiated.clear()
                remote._direct_off_until = float("inf")
                with client_device.use_browser_profile(PROFILE):
                    result = remote.request("POST", ACTION, json=cast(Any, payload), api_key=TOKEN)
                self.assertEqual(result, RESULT)
                self.assertEqual(
                    [(route, method, url) for route, method, url, _ in self.calls],
                    [("", "GET", BASE + "/v2/health"),
                     ("", "POST", BASE + "/v2/synthetic-action")],
                )

    def test_valid_proxy_strings_keep_routing_for_both_profiles(self):
        cases = (
            (PROXY, ROUTE),
            ("http://fixture:synthetic@account-proxy.invalid:8080",
             "http://fixture:synthetic@account-proxy.invalid:8080"),
            ("https://account-proxy.invalid:8443", "https://account-proxy.invalid:8443"),
            ("socks4://account-proxy.invalid:1080", "socks4a://account-proxy.invalid:1080"),
            ("socks4a://account-proxy.invalid:1080", "socks4a://account-proxy.invalid:1080"),
            (ROUTE, ROUTE),
            ("account-proxy.invalid:1080", "account-proxy.invalid:1080"),
            ("http://account-proxy.invalid", "http://account-proxy.invalid"),
            ("socks5://[2001:db8::1]:1080", "socks5h://[2001:db8::1]:1080"),
        )
        for profile in (PROFILE, "chrome152"):
            for proxy, expected_route in cases:
                with self.subTest(profile=profile, proxy=proxy):
                    self.calls.clear()
                    remote._profile_negotiated.clear()
                    remote._direct_off_until = float("inf")
                    payload = {"proxy": proxy}
                    with client_device.use_browser_profile(profile):
                        result = remote.request("POST", ACTION, json=payload, api_key=TOKEN)
                    self.assertEqual(result, RESULT)
                    expected = ([(expected_route, "GET", BASE + "/v2/health")]
                                if profile == PROFILE else [])
                    wire_action = "/v2/synthetic-action" if profile == PROFILE else ACTION
                    expected.append((expected_route, "POST", BASE + wire_action))
                    self.assertEqual(
                        [(route, method, url) for route, method, url, _ in self.calls], expected,
                    )
                    self.assertIs(self.calls[-1][3]["json"], payload)

    def test_firefox_action_maybe_sent_error_is_not_retried(self):
        for code, message in ((28, "Operation timed out after sending"),
                              (52, "Empty reply after sending"),
                              (56, "Connection reset after sending")):
            with self.subTest(code=code):
                self.calls.clear()
                remote._profile_negotiated.clear()
                remote._direct_off_until = 0.0
                self.health_error = None
                error = _CurlError(message, code)
                transport = self.transport

                def fail_action(route, method, url, kwargs):
                    if method == "POST":
                        self.calls.append((route, method, url, kwargs))
                        raise error
                    return transport(route, method, url, kwargs)

                with patch.object(self, "transport", side_effect=fail_action):
                    with client_device.use_browser_profile(PROFILE):
                        with self.assertRaises(remote.RemoteError) as caught:
                            remote.request("POST", ACTION, json={"proxy": PROXY}, api_key=TOKEN)
                self.assertTrue(caught.exception.network)
                self.assertIs(caught.exception.__cause__, error)
                self.assertEqual(
                    [(route, method, url) for route, method, url, _ in self.calls],
                    [("", "GET", BASE + "/v2/health"),
                     (ROUTE, "GET", BASE + "/v2/health"),
                     (ROUTE, "POST", BASE + "/v2/synthetic-action")],
                )

    def test_firefox_negotiation_maybe_sent_error_stops_action(self):
        self.health_error = _CurlError("Operation timed out after sending", 28)
        with client_device.use_browser_profile(PROFILE):
            with self.assertRaises(remote.RemoteError) as caught:
                remote.request("POST", ACTION, json={"proxy": PROXY}, api_key=TOKEN)
        self.assertTrue(caught.exception.network)
        self.assertIs(caught.exception.__cause__, self.health_error)
        self.assertEqual(
            [(route, method, url) for route, method, url, _ in self.calls],
            [("", "GET", BASE + "/v2/health"), (ROUTE, "GET", BASE + "/v2/health")],
        )
        self.assertEqual(remote._profile_negotiated, {})

    def test_firefox_account_proxy_stays_before_pool_fallback(self):
        fallback = "http://pool-proxy.invalid:8080"
        self.health_error = _ConnectError("synthetic account proxy cannot connect")
        transport = self.transport

        def pool_transport(route, method, url, kwargs):
            if route == fallback:
                self.calls.append((route, method, url, kwargs))
                return _Response(200, {"X-TikTok-Browser-Profile": PROFILE})
            return transport(route, method, url, kwargs)

        with patch.object(proxy_pool, "_alive_now", return_value=([PROXY, fallback], [PROXY, fallback])):
            with patch.object(self, "transport", side_effect=pool_transport):
                with client_device.use_browser_profile(PROFILE):
                    result = remote.request("POST", ACTION, json={"proxy": PROXY}, api_key=TOKEN)
        self.assertEqual(result, RESULT)
        self.assertEqual(
            [(route, method, url) for route, method, url, _ in self.calls],
            [("", "GET", BASE + "/v2/health")]
            + [(ROUTE, "GET", BASE + "/v2/health")] * proxy_pool.CHECK_TRIES
            + [(fallback, "GET", BASE + "/v2/health"),
               (ROUTE, "POST", BASE + "/v2/synthetic-action")],
        )

    def test_firefox_successful_negotiation_is_cached(self):
        with client_device.use_browser_profile(PROFILE):
            for _ in range(2):
                result = remote.request("POST", ACTION, json={"proxy": PROXY}, api_key=TOKEN)
                self.assertEqual(result, RESULT)
        self.assertEqual(
            [(route, method, url) for route, method, url, _ in self.calls],
            [("", "GET", BASE + "/v2/health"),
             (ROUTE, "GET", BASE + "/v2/health"),
             (ROUTE, "POST", BASE + "/v2/synthetic-action"),
             (ROUTE, "POST", BASE + "/v2/synthetic-action")],
        )

    def test_firefox_tls_verification_is_shared_by_health_and_action(self):
        ca_path = str(remote.SERVER_CA)
        with patch.object(remote, "_verify", return_value=ca_path) as verify:
            with client_device.use_browser_profile(PROFILE):
                result = remote.request("POST", ACTION, json={"proxy": PROXY}, api_key=TOKEN)
        self.assertEqual(result, RESULT)
        self.assertEqual(verify.call_args_list, [call(BASE), call(BASE)])
        for _, _, _, kwargs in self.calls:
            self.assertEqual(kwargs["verify"], ca_path)
            self.assertNotIn("impersonate", kwargs)

    def test_firefox_rejected_negotiation_stops_action(self):
        for status, profile in ((404, PROFILE), (503, PROFILE),
                                (200, "chrome152"), (200, None)):
            with self.subTest(status=status, profile=profile):
                self.calls.clear()
                remote._profile_negotiated.clear()
                remote._direct_off_until = 0.0
                self.health_status = status
                self.health_profile = profile
                with client_device.use_browser_profile(PROFILE):
                    with self.assertRaises(remote.RemoteError) as caught:
                        remote.request("POST", ACTION, json={"proxy": PROXY}, api_key=TOKEN)
                self.assertIn("сервер не поддерживает выбранный профиль браузера", str(caught.exception))
                self.assertFalse(caught.exception.network)
                self.assertEqual(
                    [(route, method, url) for route, method, url, _ in self.calls],
                    [("", "GET", BASE + "/v2/health"),
                     (ROUTE, "GET", BASE + "/v2/health")],
                )
                self.assertEqual(remote._profile_negotiated, {})

    def test_firefox_negotiation_network_error_stops_action(self):
        self.health_error = _ConnectError("synthetic account proxy cannot connect")
        with client_device.use_browser_profile(PROFILE):
            with self.assertRaises(remote.RemoteError) as caught:
                remote.request("POST", ACTION, json={"proxy": PROXY}, api_key=TOKEN)
        self.assertTrue(caught.exception.network)
        self.assertIs(caught.exception.__cause__, self.health_error)
        self.assertEqual(
            [(route, method, url) for route, method, url, _ in self.calls],
            [("", "GET", BASE + "/v2/health")]
            + [(ROUTE, "GET", BASE + "/v2/health")] * proxy_pool.CHECK_TRIES,
        )
        self.assertEqual(remote._profile_negotiated, {})


class CloudFailedLoginStateTest(unittest.TestCase):
    """Opaque synthetic server states; all local files use temporary roots."""

    def setUp(self):
        from modules import cloud, client_session, paths
        self.cloud, self.sessions = cloud, client_session
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(paths.use_root(self.directory))
        self.stack.enter_context(patch.object(config, "get", side_effect=lambda name, default=None: default))
        self.account = {"username": "synthetic.login.device", "password": "synthetic-password"}

    def run_login(self, response, profile):
        captured = []
        def login(method, route, **kwargs):
            self.assertEqual((method, route), ("POST", "/v1/login"))
            captured.append(kwargs["json"]["state"])
            return dict(response)
        with client_device.use_browser_profile(profile), patch.object(remote, "request", side_effect=login):
            result = self.cloud.login(self.account, "synthetic-proxy")
        self.assertNotIn("state", result)
        return result, captured

    def seed(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")

    def test_fresh_failed_login_retains_device_without_auth_marker(self):
        for profile in client_device.BROWSER_PROFILES:
            with self.subTest(profile=profile), client_device.use_browser_profile(profile):
                state = self.sessions.state_file(self.account["username"])
                kept = self.sessions.device_state_file(self.account["username"])
                result, captured = self.run_login({"ok": False, "reason": "synthetic refused", "state": "synthetic-device-after-failure"}, profile)
                self.assertFalse(result["ok"])
                self.assertEqual(captured, [None])
                self.assertEqual(kept.read_text(), "synthetic-device-after-failure")
                self.assertFalse(state.exists())
                self.assertFalse(self.sessions.has_session(self.account["username"]))

    def test_failed_login_updates_kept_device_only_state(self):
        for profile in client_device.BROWSER_PROFILES:
            with self.subTest(profile=profile), client_device.use_browser_profile(profile):
                kept = self.sessions.device_state_file(self.account["username"])
                self.seed(kept, "synthetic-old-device-only")
                _, captured = self.run_login({"ok": False, "state": "synthetic-new-device-only"}, profile)
                self.assertEqual(captured, ["synthetic-old-device-only"])
                self.assertEqual(kept.read_text(), "synthetic-new-device-only")
                self.assertFalse(self.sessions.has_session(self.account["username"]))

    def test_failed_login_updates_existing_auth_state(self):
        for profile in client_device.BROWSER_PROFILES:
            with self.subTest(profile=profile), client_device.use_browser_profile(profile):
                state = self.sessions.state_file(self.account["username"])
                self.seed(state, "synthetic-old-auth-state")
                _, captured = self.run_login({"ok": False, "state": "synthetic-preserved-auth-updated-device"}, profile)
                self.assertEqual(captured, ["synthetic-old-auth-state"])
                self.assertEqual(state.read_text(), "synthetic-preserved-auth-updated-device")
                self.assertTrue(self.sessions.has_session(self.account["username"]))

    def test_stale_auth_is_kept_without_protected_login_replay(self):
        for profile in client_device.BROWSER_PROFILES:
            with self.subTest(profile=profile), client_device.use_browser_profile(profile):
                state = self.sessions.state_file(self.account["username"])
                kept = self.sessions.device_state_file(self.account["username"])
                self.seed(state, "synthetic-stale-auth-state")
                captured = []
                def stale(method, route, **kwargs):
                    self.assertEqual(route, "/v1/login")
                    captured.append(kwargs["json"]["state"])
                    if len(captured) == 1:
                        raise remote.RemoteError("synthetic stale", status=409)
                    return {"ok": False, "state": "synthetic-fresh-device-after-stale"}
                with patch.object(remote, "request", side_effect=stale):
                    result = self.cloud.login(self.account, "synthetic-proxy")
                self.assertFalse(result["ok"])
                self.assertEqual(captured, ["synthetic-stale-auth-state"])
                self.assertFalse(kept.exists())
                self.assertEqual(state.read_text(), "synthetic-stale-auth-state")
                self.assertTrue(self.sessions.has_session(self.account["username"]))

    def test_empty_failed_response_keeps_previous_bytes(self):
        for token in (None, "", "   ", 7, {"synthetic": True}):
            with self.subTest(token=token), client_device.use_browser_profile("chrome152"):
                state = self.sessions.state_file(self.account["username"])
                self.seed(state, "synthetic-old-auth-state")
                self.run_login({"ok": False, "state": token}, "chrome152")
                self.assertEqual(state.read_text(), "synthetic-old-auth-state")

    def test_successful_login_moves_kept_device_into_auth_state(self):
        with client_device.use_browser_profile("chrome152"):
            kept = self.sessions.device_state_file(self.account["username"])
            self.seed(kept, "synthetic-kept-device")
            self.run_login({"ok": True, "state": "synthetic-new-auth-state"}, "chrome152")
            self.assertEqual(self.sessions.state_file(self.account["username"]).read_text(), "synthetic-new-auth-state")
            self.assertFalse(kept.exists())
            self.assertTrue(self.sessions.has_session(self.account["username"]))

    def test_failed_login_after_legacy_import_retains_auth_destination(self):
        for profile in client_device.BROWSER_PROFILES:
            with self.subTest(profile=profile), client_device.use_browser_profile(profile):
                cookie_file = self.sessions.session_file(self.account["username"])
                self.seed(cookie_file, "synthetic-legacy-cookies")
                captured = []
                def import_then_login(method, route, **kwargs):
                    captured.append(route)
                    if route == "/v1/accounts/import":
                        self.assertEqual(kwargs["json"]["cookies"], "synthetic-legacy-cookies")
                        return {"state": "synthetic-imported-auth-state"}
                    self.assertEqual(route, "/v1/login")
                    self.assertEqual(kwargs["json"]["state"], "synthetic-imported-auth-state")
                    return {"ok": False, "state": "synthetic-auth-with-updated-device"}
                with patch.object(remote, "request", side_effect=import_then_login):
                    self.cloud.login(self.account, "synthetic-proxy")
                self.assertEqual(captured, ["/v1/accounts/import", "/v1/login"])
                self.assertEqual(self.sessions.state_file(self.account["username"]).read_text(), "synthetic-auth-with-updated-device")
                self.assertEqual(cookie_file.read_text(), "synthetic-legacy-cookies")
                self.assertFalse(self.sessions.device_state_file(self.account["username"]).exists())

    def test_failed_state_write_preserves_original_auth_bytes(self):
        with client_device.use_browser_profile("chrome152"):
            state = self.sessions.state_file(self.account["username"])
            self.seed(state, "synthetic-original-auth")
            with patch.object(self.cloud, "_write", side_effect=OSError("synthetic no space")):
                with self.assertRaises(OSError):
                    self.run_login({"ok": False, "state": "synthetic-updated-state"}, "chrome152")
            self.assertEqual(state.read_text(), "synthetic-original-auth")

    def test_empty_existing_state_is_not_new_authentication(self):
        with client_device.use_browser_profile("chrome152"):
            state = self.sessions.state_file(self.account["username"])
            kept = self.sessions.device_state_file(self.account["username"])
            self.seed(state, "")
            self.run_login({"ok": False, "state": "synthetic-device-only"}, "chrome152")
            self.assertEqual(state.read_text(), "")
            self.assertEqual(kept.read_text(), "synthetic-device-only")


if __name__ == "__main__":
    unittest.main(verbosity=2)
