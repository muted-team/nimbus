"""Public HTTP profile selection; synthetic configuration, no account traffic."""
import contextlib
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import tempfile
from pathlib import Path
import re
import threading
import unittest
from unittest.mock import Mock, patch

from modules import config

with patch.object(config, "get", side_effect=lambda name, default=None: default):
    from modules import client_device, client_session, paths, proxy_pool, remote


class CamoufoxProfileTests(unittest.TestCase):
    def test_public_helper_copy_is_exactly_the_five_approved_canonical_files(self):
        folder = Path(__file__).resolve().parents[1] / "modules/impersonation"
        expected = {
            "__init__.py": "40bbbccf560d25070a458e9ed5b1a9da96b0c5033515d70646279124375566e8",
            "_cookies.py": "1d76647ae3d8d741e558022f561b140a37f738a260a5112233fcfef93eb03269",
            "_reference158.py": "e4f5febc3e160480c7759c45b5aea7c1ec69cf9a85f6f7e7919b39b6b8c7b237",
            "_types.py": "e4d6cea00cb9305e6662eb5ba61b58ccc18b924f85520d60d4336d23785321cb",
            "camoufox158.py": "0a91b2b8a324956c65f1c5bf462079a315506e8d36a999943a53b7323ec8274b",
        }
        self.assertEqual({path.name for path in folder.glob("*.py")}, set(expected))
        self.assertEqual({name: hashlib.sha256((folder / name).read_bytes()).hexdigest()
                          for name in expected}, expected)

    def test_selected_camoufox_constructs_measured_transport_not_a_curl_alias(self):
        from curl_cffi.const import CurlOpt
        self.assertTrue(hasattr(client_device, "new_transport_session"),
                        "selected HTTP profiles need the public transport factory")
        with client_device.use_browser_profile("camoufox158"), client_device.new_transport_session() as session:
            self.assertEqual(session.impersonate, "firefox155")
            self.assertIs(session.default_headers, False)
            self.assertEqual(dict(session.headers), {})
            self.assertEqual(session.curl_options,
                             {CurlOpt.SSL_EC_CURVES: "X25519MLKEM768:X25519:P-256:P-384:P-521",
                              CurlOpt.HTTP2_PSEUDO_HEADERS_ORDER: "mpas"})
            self.assertEqual(session.retry.count, 0)
            for sample, method, supplied, weight in (
                    ("navigation", "GET", {}, 42),
                    ("fetch-get", "GET", {"Sec-Fetch-Mode": "cors"}, 22),
                    ("fetch-post", "POST", {}, 22)):
                with self.subTest(sample=sample), patch("curl_cffi.requests.Session.request") as dispatch:
                    session.request(method, "https://synthetic.invalid", headers=supplied)
                options = dispatch.call_args.kwargs
                self.assertEqual(options["extra_fp"]["http2_stream_weight"], weight)
                self.assertEqual(options["extra_fp"]["http2_stream_exclusive"], 0)
                self.assertEqual({name.lower(): value for name, value in options["headers"]}["user-agent"],
                                 client_device.UA)
                self.assertEqual(options["accept_encoding"], "gzip, deflate, br, zstd")

    def test_missing_measured_package_never_falls_back_to_plain_firefox(self):
        with client_device.use_browser_profile("camoufox158"), patch.dict(
                "sys.modules", {"modules.impersonation": None}), patch("curl_cffi.requests.Session") as factory:
            with self.assertRaises(ImportError):
                client_device.new_transport_session()
            factory.assert_not_called()

    def test_camoufox_factory_preserves_caller_session_headers_without_duplicates(self):
        with client_device.use_browser_profile("camoufox158"):
            with client_device.new_transport_session(headers={"User-Agent": client_device.UA}) as session:
                with patch("curl_cffi.requests.Session.request") as dispatch:
                    session.get("https://synthetic.invalid", headers={"Accept": "image/*"})
                supplied = {name.lower() for name, _ in dispatch.call_args.kwargs["headers"]}
                self.assertNotIn("user-agent", supplied)
                self.assertEqual(session.headers["User-Agent"], client_device.UA)

    def test_request_cors_overrides_session_navigation_for_measured_priority(self):
        from curl_cffi import requests
        with client_device.use_browser_profile("camoufox158"), client_device.new_transport_session(
                headers={"Sec-Fetch-Mode": "navigate", "Accept-Language": "de-DE,de;q=0.9"}) as session:
            with patch.object(requests.Session, "request") as dispatch:
                session.get("https://synthetic.invalid", headers=requests.Headers({"sec-fetch-mode": "cors"}))
            options = dispatch.call_args.kwargs
            self.assertEqual(options["extra_fp"]["http2_stream_weight"], 22)
            headers = requests.Headers(session.headers)
            headers.update(options["headers"])
            self.assertEqual(headers["sec-fetch-mode"], "cors")
            self.assertEqual(headers["accept-language"], "de-DE,de;q=0.9")

    def test_measured_request_mode_matches_actual_loopback_headers(self):
        from curl_cffi import requests
        seen = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append({name.lower(): value for name, value in self.headers.raw_items()})
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        weights = []
        perform = requests.Session.request

        def dispatch(session, method, url, **options):
            weights.append(options["extra_fp"]["http2_stream_weight"])
            return perform(session, method, url, **options)

        try:
            with client_device.use_browser_profile("camoufox158"), client_device.new_transport_session(
                    headers={"Sec-Fetch-Mode": "navigate", "Accept-Language": "de-DE,de;q=0.9"},
                    trust_env=False) as session, patch.object(requests.Session, "request", new=dispatch):
                url = f"http://127.0.0.1:{server.server_port}"
                self.assertEqual(session.get(url, headers={b"sec-fetch-mode": b"cors"}, timeout=3).status_code, 200)
                self.assertEqual(seen[-1]["sec-fetch-mode"], "cors")
                self.assertEqual(seen[-1]["accept-language"], "de-DE,de;q=0.9")
                self.assertEqual(session.get(url, headers={"sec-fetch-mode": None, "accept-language": None}, timeout=3).status_code, 200)
                self.assertNotIn("sec-fetch-mode", seen[-1])
                self.assertNotIn("accept-language", seen[-1])
                self.assertEqual(weights, [22, 22])
                self.assertEqual(session.headers["Sec-Fetch-Mode"], "navigate")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_client_measured_transport_request_classes_on_real_loopback_http(self):
        seen = []

        class Handler(BaseHTTPRequestHandler):
            def reply(self):
                seen.append(list(self.headers.raw_items()))
                body = b'{"ok":true}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self.reply()

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                self.reply()

            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        try:
            with client_device.use_browser_profile("camoufox158"), client_device.new_transport_session(
                    headers={"User-Agent": client_device.UA}, trust_env=False) as session:
                url = f"http://127.0.0.1:{server.server_port}"
                self.assertTrue(session.get(url, timeout=3).json()["ok"])
                self.assertTrue(session.get(url, headers=client_device.fetch_headers(), timeout=3).json()["ok"])
                self.assertTrue(session.post(url, headers={"Content-Type": "application/json"},
                                             json={"synthetic": True}, timeout=3).json()["ok"])
                for rows in seen:
                    names = [name.lower() for name, _ in rows]
                    self.assertEqual(len(names), len(set(names)))
                    self.assertEqual({name.lower(): value for name, value in rows}["user-agent"], client_device.UA)
                self.assertEqual({name.lower(): value for name, value in seen[0]}["upgrade-insecure-requests"], "1")
                self.assertNotIn("upgrade-insecure-requests", {name.lower() for name, _ in seen[1]})
                self.assertEqual({name.lower(): value for name, value in seen[2]}["content-type"], "application/json")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
        self.assertFalse(thread.is_alive())

    def test_chrome_and_firefox_keep_their_existing_curl_constructor_options(self):
        self.assertTrue(hasattr(client_device, "new_transport_session"),
                        "selected HTTP profiles need the public transport factory")
        for profile in ("chrome152", "firefox155"):
            with self.subTest(profile=profile), client_device.use_browser_profile(profile), \
                    patch("curl_cffi.requests.Session") as factory:
                session = client_device.new_transport_session(proxies={"all": "synthetic-route"})
                self.assertIs(session, factory.return_value)
                factory.assert_called_once_with(impersonate=profile, proxies={"all": "synthetic-route"})

    def test_camoufox_is_selectable_with_its_measured_158_user_agent(self):
        self.assertEqual(client_device.BROWSER_PROFILES,
                         ("chrome152", "firefox155", "camoufox158"))
        previous = client_device.browser_profile()
        with client_device.use_browser_profile("camoufox158"):
            self.assertEqual(client_device.browser_profile(), "camoufox158")
            self.assertEqual(client_device.UA,
                             "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:158.0) "
                             "Gecko/20100101 Firefox/158.0")
            self.assertEqual(client_device.SEC_CH_UA, {})
        self.assertEqual(client_device.browser_profile(), previous)

    def test_proxy_health_uses_the_selected_public_session_factory(self):
        from curl_cffi import requests
        url = "http://synthetic.invalid:8080"
        session = Mock()
        session.__enter__ = Mock(return_value=session)
        session.__exit__ = Mock(return_value=False)
        with client_device.use_browser_profile("camoufox158"), contextlib.ExitStack() as stack:
            factory = stack.enter_context(patch.object(client_device, "new_transport_session", return_value=session))
            stack.enter_context(patch.object(proxy_pool, "_ping", return_value=(1, "")))
            stack.enter_context(patch.object(proxy_pool, "_maybe_refresh_country", return_value=""))
            stack.enter_context(patch.object(proxy_pool, "rotation", return_value={}))
            stack.enter_context(patch.object(proxy_pool, "exit_geo", return_value={}))
            stack.enter_context(patch.object(requests, "get", side_effect=AssertionError("raw curl target is forbidden")))
            result = proxy_pool._probe(url)
        self.assertTrue(result["ok"])
        factory.assert_called_once_with()
        self.assertEqual(session.get.call_args.args[0], proxy_pool.CHECK_URL)
        self.assertNotIn("impersonate", session.get.call_args.kwargs)

    def test_proxy_geography_uses_the_selected_public_session_factory(self):
        from curl_cffi import requests
        session = Mock()
        session.__enter__ = Mock(return_value=session)
        session.__exit__ = Mock(return_value=False)
        session.get.return_value.json.return_value = {
            "ip": "192.0.2.1", "country": "US", "timezone": "America/New_York", "org": "AS1 Synthetic"}
        with client_device.use_browser_profile("camoufox158"), patch.object(
                client_device, "new_transport_session", return_value=session) as factory, patch.object(
                proxy_pool, "_geo_cache", {}), patch.object(requests, "Session", side_effect=AssertionError("raw curl target is forbidden")):
            result = proxy_pool.exit_geo("socks5://synthetic.invalid:1080")
        self.assertEqual(result["country"], "US")
        factory.assert_called_once_with()
        self.assertEqual(session.proxies, {"all": "socks5h://synthetic.invalid:1080"})
        self.assertNotIn("impersonate", session.get.call_args.kwargs)

    def test_new_exit_ip_check_uses_the_selected_public_session_factory(self):
        from curl_cffi import requests
        session = Mock()
        session.__enter__ = Mock(return_value=session)
        session.__exit__ = Mock(return_value=False)
        session.get.return_value.text = "192.0.2.1\n"
        with client_device.use_browser_profile("camoufox158"), patch.object(
                client_device, "new_transport_session", return_value=session) as factory, patch.object(
                requests, "Session", side_effect=AssertionError("raw curl target is forbidden")):
            result = proxy_pool._exit_ip("socks5://synthetic.invalid:1080")
        self.assertEqual(result, "192.0.2.1")
        factory.assert_called_once_with()
        self.assertEqual(session.proxies, {"all": "socks5h://synthetic.invalid:1080"})

    def test_country_page_uses_the_selected_public_session_factory(self):
        from curl_cffi import requests
        from modules import profiles
        session = Mock()
        session.__enter__ = Mock(return_value=session)
        session.__exit__ = Mock(return_value=False)
        session.get.return_value.iter_content.return_value = [b'{"region":"US"}']
        with client_device.use_browser_profile("camoufox158"), patch.object(
                client_device, "new_transport_session", return_value=session) as factory, patch.object(
                requests, "Session", side_effect=AssertionError("raw curl target is forbidden")), patch.object(
                profiles, "_REGION_RE", re.compile(r'"region":"([A-Z]{2})"'), create=True):
            result = proxy_pool._country_probe("socks5://synthetic.invalid:1080")
        self.assertEqual(result, "US")
        factory.assert_called_once_with()
        self.assertNotIn("impersonate", session.get.call_args.kwargs)
        self.assertEqual(session.get.call_args.kwargs["proxies"], {"all": "socks5h://synthetic.invalid:1080"})
        session.get.return_value.close.assert_called_once_with()

    def test_avatar_cdn_download_uses_the_selected_public_session_factory(self):
        from curl_cffi import requests
        from modules import avatars, profiles
        session = Mock()
        session.__enter__ = Mock(return_value=session)
        session.__exit__ = Mock(return_value=False)
        session.get.return_value.status_code = 200
        session.get.return_value.content = b"synthetic-image"
        session.get.return_value.headers = {"content-type": "image/jpeg"}
        with client_device.use_browser_profile("camoufox158"), patch.object(
                client_device, "new_transport_session", return_value=session) as factory, patch.object(
                requests, "Session", side_effect=AssertionError("raw curl target is forbidden")), patch.object(
                avatars, "source_of", return_value="synthetic-source"), patch.object(
                avatars, "stored_source", return_value=None), patch.object(
                avatars, "store", return_value=True) as store, patch.object(profiles, "_touch"):
            profiles._avatar_via("synthetic.user", "https://cdn.invalid/image.jpg", "socks5://synthetic.invalid:1080")
        factory.assert_called_once_with(proxies={"all": "socks5h://synthetic.invalid:1080"})
        store.assert_called_once_with("synthetic.user", b"synthetic-image", "image/jpeg", "synthetic-source")

    def test_upload_session_constructs_the_selected_measured_transport_without_cookies(self):
        from modules import cloud
        with client_device.use_browser_profile("camoufox158"), cloud._tos_session(
                "socks5://synthetic.invalid:1080") as session:
            self.assertEqual(session.impersonate, "firefox155")
            self.assertIs(session.default_headers, False)
            self.assertEqual(session.proxies, {"all": "socks5h://synthetic.invalid:1080"})
            self.assertEqual(session.headers["User-Agent"], client_device.UA)
            self.assertEqual(list(session.cookies.jar), [])
            self.assertEqual(session.retry.count, 0)

    def test_batch_worker_constructs_measured_transport_before_any_media_work(self):
        from modules import batch_publish
        worker = batch_publish.BatchWorker([], "", "", 0, 0, "synthetic.user", 0,
                                           proxy="socks5://synthetic.invalid:1080", creatives="unique")
        worker._run_lock.acquire()
        with client_device.use_browser_profile("camoufox158"), patch.object(proxy_pool, "bind") as bind:
            try:
                worker._run()
                session = worker._session
                self.assertIsNotNone(session)
                self.assertEqual(session.impersonate, "firefox155")
                self.assertIs(session.default_headers, False)
                self.assertEqual(session.proxies, {"all": "socks5h://synthetic.invalid:1080"})
                self.assertEqual(session.retry.count, 0)
                bind.assert_called_once_with(session, None)
                self.assertEqual(worker.get_status()["posts_done"], 0)
            finally:
                if worker._session is not None:
                    worker._session.close()
                if worker._run_lock.locked():
                    worker._run_lock.release()

    def test_actual_old_server_is_rejected_before_protected_http_dispatch(self):
        seen = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append((self.command, self.path))
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_POST(self):
                seen.append((self.command, self.path))
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        try:
            with contextlib.ExitStack() as stack:
                stack.enter_context(patch.object(remote, "base", return_value=f"http://127.0.0.1:{server.server_port}"))
                stack.enter_context(patch.object(remote, "_profile_negotiated", {}))
                stack.enter_context(patch.object(remote, "_local", threading.local()))
                stack.enter_context(patch.object(remote, "_direct_off_until", 0))
                stack.enter_context(patch.object(config, "server_wait_min", return_value=0))
                stack.enter_context(client_device.use_browser_profile("camoufox158"))
                with self.assertRaises(remote.RemoteError) as caught:
                    remote.request("POST", "/v1/login", json={"username": "synthetic.user"},
                                   api_key="synthetic-key")
                self.assertTrue(caught.exception.stop_account)
                self.assertFalse(caught.exception.outcome_unknown)
                self.assertEqual(seen, [("GET", "/v2/health")])
                for session in remote._local.sessions.values():
                    session.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
        self.assertFalse(thread.is_alive())

    def test_camoufox_never_reads_or_migrates_chrome_or_firefox_cookie_state(self):
        previous = client_device.browser_profile()
        with tempfile.TemporaryDirectory() as temporary, paths.use_root(temporary):
            root = Path(temporary)
            expected = {"chrome152": root / "sessions",
                        "firefox155": root / "sessions" / "firefox155",
                        "camoufox158": root / "sessions" / "camoufox158"}
            for profile in ("chrome152", "firefox155"):
                with client_device.use_browser_profile(profile):
                    state = client_session.state_file("synthetic.user")
                    state.write_text("synthetic-" + profile, encoding="utf-8")
            originals = {path: path.read_bytes() for path in root.rglob("*.state")}
            for profile, folder in expected.items():
                with self.subTest(profile=profile), client_device.use_browser_profile(profile):
                    self.assertEqual(client_session.session_directory(), folder)
                    filename = ("tiktok_cookies.json" if profile == "chrome152"
                                else f"tiktok_cookies.{profile}.json")
                    self.assertEqual(client_session.session_file(), root / filename)
            with client_device.use_browser_profile("camoufox158"):
                self.assertFalse(client_session.has_session("synthetic.user"))
                self.assertFalse(client_session.state_file("synthetic.user").exists())
            self.assertEqual({path: path.read_bytes() for path in originals}, originals)
        self.assertEqual(client_device.browser_profile(), previous)


if __name__ == "__main__":
    unittest.main()
