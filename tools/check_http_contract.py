"""Synthetic client HTTP/storage regressions; run as a separate process.

    python tools/check_http_contract.py

Uses the client's existing dependencies, real HTTP handlers and local storage.
Only loopback HTTP is permitted. All configuration, accounts, media and session
fixtures live in a temporary data root, never in the checkout or user profile.
"""
import argparse
import contextlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import itertools
import json
import os
from pathlib import Path
from queue import Queue
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
KEY = "synthetic-qa-key"
USER = "synthetic.qa"


class Upstream(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def reply(self, status, body, headers=None):
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        if self.server.confirm_profile:
            self.send_header("X-TikTok-Browser-Profile", self.headers.get("X-TikTok-Browser-Profile", "chrome152"))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def handle_api(self):
        path = urlsplit(self.path).path
        n = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(n) if n else b""
        body = json.loads(raw) if raw and self.headers.get("Content-Type", "").startswith("application/json") else raw
        self.server.seen.append({"method": self.command, "path": path, "body": body,
                                 "profile": self.headers.get("X-TikTok-Browser-Profile"),
                                 "authorization": self.headers.get("Authorization")})
        if path == "/v2/health":
            self.reply(200, {"ok": True})
            return
        status, payload, headers = self.server.respond(self.command, path, body)
        self.reply(status, payload, headers)

    do_GET = do_POST = do_OPTIONS = handle_api


class ClientHTTPAcceptance(unittest.TestCase):
    def setUp(self):
        stack = self.stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="client-http-", dir=RUNTIME)))
        stack.enter_context(paths.use_root(self.root))
        self.upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        self.upstream.daemon_threads = True
        self.upstream.seen = []
        self.upstream.confirm_profile = True
        self.upstream.respond = lambda *a: (200, {}, {})
        self.base = f"http://127.0.0.1:{self.upstream.server_port}"
        config.update({"license_key": KEY, "server_url": self.base, "host": "127.0.0.1",
                       "proxy_enabled": False, "execution_modes": {"login": 0, "publish": 0, "logout": 0},
                       "server_wait_min": 1})
        previous = os.environ.get("NIMBUS_SERVER")
        os.environ["NIMBUS_SERVER"] = self.base
        stack.callback(lambda: os.environ.pop("NIMBUS_SERVER", None) if previous is None else os.environ.__setitem__("NIMBUS_SERVER", previous))
        self.start_server(self.upstream)
        self.local = ClientServer(("127.0.0.1", 0), main.Handler)
        self.local.daemon_threads = True
        self.local.require_auth = False
        self.local.data_root = self.root
        self.start_server(self.local)
        self.http = http.client.HTTPConnection("127.0.0.1", self.local.server_port, timeout=4)
        stack.callback(self.http.close)

    def start_server(self, server):
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def stop():
            server.shutdown()
            server.server_close()
            thread.join(4)
            self.assertFalse(thread.is_alive(), "Test HTTP server did not stop")

        self.stack.callback(stop)

    def api(self, method, path, body=None, headers=None, connection=None):
        connection = connection or self.http
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
        connection.request(method, path, data, {"Content-Type": "application/json", **(headers or {})})
        response = connection.getresponse()
        return response.status, json.loads(response.read())

    def start_api(self, method, path, body):
        replies = []

        def request():
            connection = http.client.HTTPConnection("127.0.0.1", self.local.server_port, timeout=8)
            try:
                replies.append(self.api(method, path, body, connection=connection))
            except Exception as exc:
                replies.append(exc)
            finally:
                connection.close()

        thread = threading.Thread(target=request, daemon=True)
        thread.start()
        return thread, replies

    def requests_at(self, path):
        return [r for r in self.upstream.seen if r["path"] == path]

    def test_protected_operations_are_one_shot_over_http(self):
        protected = ("/v1/login", "/v1/photos/upload", "/v1/photos/publish", "/v1/videos/upload",
                     "/v1/videos/publish", "/v1/profile/update", "/v1/posts/delete", "/v1/logout",
                     "/v1/register", "/v1/register/" + "a" * 32 + "/cancel",
                     "/v3/browser/jobs/synthetic/cancel")
        for profile in client_device.BROWSER_PROFILES:
            with client_device.use_browser_profile(profile):
                for path in protected:
                    for status in (307, 308, 409, 503):
                        with self.subTest(profile=profile, path=path, status=status):
                            self.upstream.seen.clear()
                            self.upstream.respond = lambda *a: (status, {"detail": "synthetic refusal"},
                                                               {"Location": self.base + "/would-replay", "Retry-After": "1"})
                            with self.assertRaises(remote.RemoteError) as error:
                                remote.request("POST", path, json={"synthetic": True})
                            actions = [r for r in self.upstream.seen if r["method"] == "POST"]
                            self.assertEqual(len(actions), 1, actions)
                            self.assertNotEqual(actions[0]["path"], "/would-replay")
                            self.assertTrue(error.exception.stop_account)
                            self.assertFalse(error.exception.network)

    def test_unknown_publication_preserves_state_and_has_no_item_or_retry(self):
        state = client_session.state_file(USER)
        state.write_text("SYNTHETIC_KEPT")
        bad = (None, [], "not-an-object", {}, {"ok": True, "verdict": "ok", "item_id": True},
               {"ok": True, "verdict": "ok", "item_id": "0"},
               {"ok": True, "verdict": "unknown", "item_id": "123"})
        for payload in bad:
            with self.subTest(payload=payload):
                self.upstream.seen.clear()
                self.upstream.respond = lambda *a: (200, payload, {})
                result = cloud.publish_photo_items(USER, "", [{"ticket": "SYNTHETIC", "frame": "SYNTHETIC"}])
                self.assertFalse(result["ok"])
                self.assertEqual(result["verdict"], "unknown")
                self.assertIsNone(result["item_id"])
                self.assertTrue(result["stop_account"])
                self.assertFalse(result["retriable"])
                self.assertFalse(result["network"])
                self.assertEqual(state.read_text(), "SYNTHETIC_KEPT")
                self.assertEqual(len([r for r in self.upstream.seen if r["method"] == "POST"]), 1)

    def test_rejected_key_cannot_replace_stored_key_or_dispatch_account_action(self):
        self.upstream.respond = lambda *a: (401, {"detail": "invalid synthetic key"}, {})
        with self.assertRaises(remote.RemoteError):
            remote.set_key("synthetic-rejected-key")
        self.assertEqual(config.get("license_key"), KEY)
        self.assertEqual(self.upstream.seen[0]["authorization"], "Bearer synthetic-rejected-key")
        self.upstream.seen.clear()
        config.update({"license_key": ""})
        with self.assertRaises(remote.RemoteError):
            remote.request("POST", "/v1/login", json={})
        self.assertEqual(self.upstream.seen, [])

    def test_unconfirmed_nonchrome_negotiation_stops_before_account_mutation(self):
        self.upstream.confirm_profile = False
        for profile in client_device.BROWSER_PROFILES:
            if profile == "chrome152":
                continue
            with self.subTest(profile=profile), client_device.use_browser_profile(profile):
                with self.assertRaises(remote.RemoteError):
                    remote.request("POST", "/v1/login", json={"username": USER, "password": "Synthetic-password"})
                self.assertFalse(any(r["method"] == "POST" for r in self.upstream.seen))

    def test_confirmed_email_alias_login_persists_platform_identity_not_credentials(self):
        alias = "fixture@example.invalid"
        account = {"username": alias, "password": "Synthetic-password"}
        status, _ = self.api("POST", "/api/accounts", account)
        self.assertEqual(status, 200)
        self.upstream.respond = lambda *a: (200, {"ok": True, "verdict": "ok", "state_saved": True,
            "state": "SYNTHETIC_EMAIL_STATE", "profile": {"user_id": "123456", "unique_id": "actual.qa",
            "sec_uid": "synthetic-sec-uid", "nickname": "Synthetic 🌷"}}, {})
        status, result = self.api("POST", "/api/login", {"username": alias})
        self.assertEqual(status, 200)
        self.assertTrue(result["ok"], result)
        self.assertEqual(client_session.state_file(alias).read_text(), "SYNTHETIC_EMAIL_STATE")
        row = profiles.get(alias)
        self.assertIsNotNone(row, "Confirmed email login must persist the platform UID/name in SQLite")
        self.assertEqual(row["user_id"], "123456")
        self.assertEqual(row["unique_id"], "actual.qa")
        self.assertEqual(row["nickname"], "Synthetic 🌷")
        public_status, public = self.api("GET", "/api/accounts")
        self.assertEqual(public_status, 200)
        self.assertNotIn(account["password"], json.dumps(public))
        self.assertNotIn("SYNTHETIC_EMAIL_STATE", json.dumps(public))
        self.assertEqual(len([r for r in self.upstream.seen if r["method"] == "POST"]), 1)

    def test_profile_edit_receipt_prevents_duplicate_until_real_readback(self):
        accounts.add_account({"username": USER, "password": "Synthetic-password"})
        config.update({"proxy_enabled": True, "proxies": [self.base], "proxies_login": [self.base]})
        state = client_session.state_file(USER)
        state.write_text("SYNTHETIC_KEPT")

        def respond(method, path, body):
            if path.endswith("/profile/plan"):
                return 200, {"state": "SYNTHETIC_KEPT", "data": {"verdict": "planned", "network_performed": False,
                                                                        "requested": body["changes"]}}, {}
            if path.endswith("/profile/info"):
                return 200, {"state": "SYNTHETIC_KEPT", "data": {"verdict": "observed", "before": {
                    "user_id": "123", "unique_id": USER, "nickname": "Synthetic"}, "policies": {}}}, {}
            return 503, {"detail": "synthetic reply lost"}, {"Retry-After": "1"}

        self.upstream.respond = respond
        body = {"username": USER, "changes": {"nickname": "Synthetic 🌷"}, "expected_user_id": "123",
                "acknowledge_cooldown": True}
        status, result = self.api("POST", "/api/tiktok-profile/update", body)
        self.assertEqual(status, 200, result)
        self.assertEqual(result["verdict"], "unknown")
        receipt = profile_edit._read(USER)
        self.assertFalse(receipt["reconciled"])
        self.assertEqual(receipt["requested"]["nickname"], "Synthetic 🌷")
        self.assertEqual(self.api("POST", "/api/tiktok-profile/update", body)[0], 400)
        self.assertEqual(len(self.requests_at("/v1/profile/update")), 1)
        self.assertEqual(state.read_text(), "SYNTHETIC_KEPT")
        status, info = self.api("POST", "/api/tiktok-profile/info", {"username": USER})
        self.assertEqual(status, 200)
        self.assertEqual(info["last_result"]["verdict"], "unknown")
        self.assertTrue(profile_edit._read(USER)["reconciled"])

    def test_camoufox_profile_uid_conflict_blocks_http_purge_and_upload(self):
        from modules import db, purge

        self.stack.enter_context(patch.object(client_device, "_DEFAULT_PROFILE", "camoufox158"))
        accounts._write_json(self.root / "accounts.json", {"accounts": [{
            "username": USER, "password": "Synthetic-password", "registration_proxy": self.base}]})
        profiles.save_identity(USER, {"user_id": "111", "unique_id": USER, "nickname": "Kept"})
        profiles.save_posts(USER, [{"id": "5001", "desc": "Kept post"}])
        client_session.state_file(USER).write_text("SYNTHETIC_KEPT")

        def respond(method, path, body):
            if path.endswith("/profile/info"):
                return 200, {"state": "SYNTHETIC_FOREIGN", "data": {"verdict": "observed", "before": {
                    "user_id": "222", "unique_id": "foreign.qa", "nickname": "Foreign"}, "policies": {}}}, {}
            return 200, {"data": {}, "deleted": 0, "failed": [], "total": 0}, {}

        self.upstream.respond = respond
        finished = threading.Event()
        run_purge = purge.run_manual

        def tracked_purge(*args):
            try:
                with paths.use_root(self.root), client_device.use_browser_profile("camoufox158"):
                    run_purge(*args)
            finally:
                finished.set()

        with patch.object(purge, "run_manual", side_effect=tracked_purge):
            status, info = self.api("POST", "/api/tiktok-profile/info", {"username": USER})
            self.assertEqual(status, 400, info)
            status, purge_out = self.api("POST", "/api/accounts/purge", {"username": USER, "count": -1})
            self.assertEqual(status, 202, purge_out)
            self.assertTrue(finished.wait(4), "Queued synthetic purge never finished")
        with self.assertRaises(remote.RemoteError):
            cloud.upload_photos(USER, "", [b"SYNTHETIC_UPLOAD"])
        mutations = [request for request in self.upstream.seen
                     if request["path"].endswith(("/posts/delete", "/photos/upload", "/photos/publish"))]
        self.assertEqual(mutations, [], "Foreign profile state must never reach a mutation")
        self.assertEqual(len(self.requests_at("/v2/profile/info")), 1)
        self.assertTrue(profiles.identity_conflict(USER))
        self.assertEqual(client_session.state_file(USER).read_text(), "SYNTHETIC_KEPT")
        with contextlib.closing(db.connect()) as conn:
            self.assertEqual(conn.execute("SELECT user_id, unique_id, nickname FROM profiles WHERE username = ?", (USER,)).fetchone(),
                             ("111", USER, "Kept"))
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM posts WHERE username = ?", (USER,)).fetchone()[0], 1)

    def test_camoufox_malformed_session_uids_are_terminal(self):
        with client_device.use_browser_profile("camoufox158"):
            profiles.save_identity(USER, {"user_id": "111", "unique_id": USER})
            state = client_session.state_file(USER)
            for uid in ("01", "00", "-1", "not-a-uid", "1" * 65, True):
                with self.subTest(uid=uid):
                    state.write_text("SYNTHETIC_KEPT")
                    self.upstream.respond = lambda *args: (200, {"state": "SYNTHETIC_UNCONFIRMED", "data": {
                        "alive": True, "uid": uid, "http_status": 200, "message": "success", "code": 0}}, {})
                    result = cloud.session_check(USER, "")
                    self.assertIs(result["alive"], False)
                    self.assertTrue(result["stop_account"])
                    self.assertEqual(result["verdict"], "unknown")
                    self.assertEqual(state.read_text(), "SYNTHETIC_KEPT")
                    self.assertFalse(profiles.identity_conflict(USER), "Malformed evidence is not a confirmed UID mismatch")

    def test_camoufox_campaign_stops_after_malformed_uid_without_upstream_mutation(self):
        from modules import campaign, signin

        with client_device.use_browser_profile("camoufox158"):
            accounts.add_account({"username": USER, "password": "Synthetic-password"})
            profiles.save_identity(USER, {"user_id": "111", "unique_id": USER})
            client_session.state_file(USER).write_text("SYNTHETIC_KEPT")
            self.upstream.respond = lambda *args: (200, {"data": {
                "alive": True, "uid": "not-a-uid", "http_status": 200, "message": "success", "code": 0}}, {})
            with patch.object(campaign, "_stop_requested", return_value=False), \
                    patch.object(campaign, "_worker_set"), patch.object(campaign, "_worker_clear"), \
                    patch.object(campaign, "_pause_account") as paused, patch.object(campaign, "_fail_account") as failed, \
                    patch.object(campaign, "_read_notices") as notices, patch.object(signin, "run") as login, \
                    patch.object(campaign.batch_publish, "BatchWorker") as publication:
                campaign._worker_run(accounts.load_account(USER), [], "", "", 0, 0, 1, None, itertools.count())
            paused.assert_called_once_with(USER)
            failed.assert_called_once()
            login.assert_not_called()
            notices.assert_not_called()
            publication.assert_not_called()
        self.assertEqual([r["path"] for r in self.upstream.seen if r["method"] == "POST"], ["/v2/session/check"])

    def test_http_delete_readd_clears_only_the_deleted_accounts_quarantine(self):
        self.stack.enter_context(patch.object(client_device, "_DEFAULT_PROFILE", "camoufox158"))
        alias = "fixture@example.invalid"
        account = {"username": alias, "password": "Synthetic-password"}
        self.assertEqual(self.api("POST", "/api/accounts", account)[0], 200)
        profiles.save_identity(alias, {"user_id": "111", "unique_id": "kept.qa"})
        profiles.save_identity("unrelated.qa", {"user_id": "333", "unique_id": "unrelated.qa"})
        profiles.mark_identity_conflict("unrelated.qa")
        phase = {"uid": "222", "handle": "foreign.qa"}
        self.upstream.respond = lambda *args: (200, {"ok": True, "verdict": "ok", "state": "SYNTHETIC_FRESH",
            "profile": {"user_id": phase["uid"], "unique_id": phase["handle"]}}, {})
        status, result = self.api("POST", "/api/login", {"username": alias})
        self.assertEqual(status, 200)
        self.assertTrue(result["ok"])
        self.assertTrue(result["identity_conflict"])
        self.assertTrue(profiles.identity_conflict(alias))
        phase.update(uid="111", handle="kept.qa")
        self.assertTrue(self.api("POST", "/api/login", {"username": alias})[1]["identity_conflict"],
                        "Ordinary relogin must not remove quarantine")
        status, removed = self.api("POST", "/api/accounts/delete", {"username": alias, "new_device": True})
        self.assertEqual(status, 200, removed)
        self.assertTrue(removed["ok"])
        self.assertFalse(profiles.identity_conflict(alias), "Explicit successful deletion must clear process quarantine")
        self.assertIsNone(profiles.get(alias))
        self.assertTrue(profiles.identity_conflict("unrelated.qa"))
        self.assertEqual(self.api("POST", "/api/accounts", account)[0], 200)
        status, result = self.api("POST", "/api/login", {"username": alias})
        self.assertEqual(status, 200, result)
        self.assertTrue(result["ok"])
        self.assertFalse(result.get("identity_conflict", False))
        self.assertFalse(result.get("stop_account", False))
        self.assertEqual(profiles.get(alias)["user_id"], "111")
        self.assertEqual(len(self.requests_at("/v2/login")), 3)

    def test_obsolete_readback_cannot_quarantine_a_readded_account(self):
        self.stack.enter_context(patch.object(client_device, "_DEFAULT_PROFILE", "camoufox158"))
        account = {"username": USER, "password": "Synthetic-password"}
        self.assertEqual(self.api("POST", "/api/accounts", account)[0], 200)
        accounts._write_json(self.root / "accounts.json", {"accounts": [{**account, "registration_proxy": self.base}]})
        profiles.save_identity(USER, {"user_id": "111", "unique_id": USER})
        client_session.state_file(USER).write_text("SYNTHETIC_OLD")
        entered, release = threading.Event(), threading.Event()

        def respond(method, path, body):
            if path.endswith("/profile/info"):
                entered.set()
                self.assertTrue(release.wait(6), "Old readback was not released")
                return 200, {"state": "SYNTHETIC_FOREIGN", "data": {"verdict": "observed", "before": {
                    "user_id": "222", "unique_id": "foreign.qa", "nickname": "Foreign"}}}, {}
            if path.endswith("/profiles"):
                return 200, {"profiles": [{"username": USER, "profile": {"user_id": "111", "unique_id": USER,
                    "method": "ssr"}, "posts": None, "avatar_url": ""}], "failed": []}, {}
            return 200, {"ok": True, "verdict": "ok", "state": "SYNTHETIC_REPLACEMENT",
                         "profile": {"user_id": "111", "unique_id": USER}}, {}

        self.upstream.respond = respond
        deletion_stage = Queue()
        deletion_thread = []
        keep_device, request_lock, write_registry = accounts._keep_device, cloud._lock, accounts._write_json

        def tracked_keep(*args, **kwargs):
            keep_device(*args, **kwargs)
            deletion_thread.append(threading.get_ident())

        def tracked_lock(username):
            if threading.get_ident() in deletion_thread:
                deletion_stage.put("request-lock")
            return request_lock(username)

        def tracked_registry(*args, **kwargs):
            write_registry(*args, **kwargs)
            if threading.get_ident() in deletion_thread:
                deletion_stage.put("registry-deleted")

        self.stack.enter_context(patch.object(accounts, "_keep_device", side_effect=tracked_keep))
        self.stack.enter_context(patch.object(cloud, "_lock", side_effect=tracked_lock))
        self.stack.enter_context(patch.object(accounts, "_write_json", side_effect=tracked_registry))
        reader, replies = self.start_api("POST", "/api/tiktok-profile/info", {"username": USER})
        deleter = None
        try:
            self.assertTrue(entered.wait(4), "Readback never reached upstream")
            deleter, deleted = self.start_api("POST", "/api/accounts/delete", {"username": USER, "new_device": True})
            if deletion_stage.get(timeout=4) == "request-lock":
                # Fixed deletion waits for the readback; the old code instead
                # reaches registry deletion while that response is pending.
                release.set()
                reader.join(4)
            deleter.join(4)
            self.assertFalse(deleter.is_alive())
            self.assertEqual(deleted[0][0], 200, deleted)
            self.assertEqual(self.api("POST", "/api/accounts", account)[0], 200)
            config.update({"proxy_enabled": True, "proxies": [self.base], "proxies_login": [self.base]})
            status, refreshed = self.api("POST", "/api/profiles/fetch", {"usernames": [USER], "posts": False})
            self.assertEqual(status, 200, refreshed)
            self.assertEqual(profiles.get(USER)["user_id"], "111")
        finally:
            release.set()
            reader.join(4)
            if deleter:
                deleter.join(4)
        self.assertFalse(reader.is_alive())
        self.assertIsInstance(replies[0], tuple, replies)
        self.assertGreaterEqual(replies[0][0], 400)
        self.assertFalse(profiles.identity_conflict(USER), "Obsolete UID evidence must not quarantine the replacement")
        self.assertEqual(self.api("POST", "/api/login", {"username": USER})[1]["ok"], True)
        self.assertEqual(client_session.state_file(USER).read_text(), "SYNTHETIC_REPLACEMENT")
        self.assertFalse(profiles.identity_conflict(USER))

    def test_invalidated_readback_is_rejected_before_uid_quarantine(self):
        self.stack.enter_context(patch.object(client_device, "_DEFAULT_PROFILE", "camoufox158"))
        account = {"username": USER, "password": "Synthetic-password", "registration_proxy": self.base}
        accounts._write_json(self.root / "accounts.json", {"accounts": [account]})
        profiles.save_identity(USER, {"user_id": "111", "unique_id": USER})
        client_session.state_file(USER).write_text("SYNTHETIC_OLD")
        entered, release = threading.Event(), threading.Event()

        def respond(method, path, body):
            if path.endswith("/profile/info"):
                entered.set()
                self.assertTrue(release.wait(6))
                return 200, {"state": "SYNTHETIC_FOREIGN", "data": {"verdict": "observed", "before": {
                    "user_id": "222", "unique_id": "foreign.qa", "nickname": "Foreign"}}}, {}
            return 200, {"ok": True, "verdict": "ok", "state": "SYNTHETIC_REPLACEMENT",
                         "profile": {"user_id": "111", "unique_id": USER}}, {}

        self.upstream.respond = respond
        reader, replies = self.start_api("POST", "/api/tiktok-profile/info", {"username": USER})
        try:
            self.assertTrue(entered.wait(4))
            self.assertEqual(self.api("POST", "/api/accounts/clear-session", {"username": USER, "new_device": True})[0], 200)
            client_session.state_file(USER).write_text("SYNTHETIC_REPLACEMENT")
        finally:
            release.set()
            reader.join(4)
        self.assertFalse(reader.is_alive())
        self.assertGreaterEqual(replies[0][0], 400, replies)
        self.assertFalse(profiles.identity_conflict(USER), "Obsolete evidence must not quarantine a newer generation")
        self.assertEqual(client_session.state_file(USER).read_text(), "SYNTHETIC_REPLACEMENT")
        self.assertTrue(self.api("POST", "/api/login", {"username": USER})[1]["ok"])
        self.assertFalse(profiles.identity_conflict(USER))

    def test_old_delete_cannot_clear_readded_accounts_fresh_quarantine(self):
        from modules import avatars, db

        self.stack.enter_context(patch.object(client_device, "_DEFAULT_PROFILE", "camoufox158"))
        account = {"username": USER, "password": "Synthetic-password"}
        self.assertEqual(self.api("POST", "/api/accounts", account)[0], 200)
        profiles.save_identity(USER, {"user_id": "111", "unique_id": USER})
        client_session.state_file(USER).write_text("SYNTHETIC_OLD")
        cleanup_entered, release_cleanup = threading.Event(), threading.Event()
        add_entered = threading.Event()
        cleanup_owns_registry = []
        remove, add = avatars.remove, accounts.add_account

        def delayed_cleanup(username):
            cleanup_owns_registry.append(accounts._lock._is_owned())
            cleanup_entered.set()
            self.assertTrue(release_cleanup.wait(6), "Old deletion cleanup was not released")
            return remove(username)

        def observed_add(body):
            add_entered.set()
            return add(body)

        self.upstream.respond = lambda *args: (200, {"ok": True, "verdict": "ok", "state": "FOREIGN_FRESH",
            "profile": {"user_id": "222", "unique_id": "foreign.qa"}}, {})
        with patch.object(avatars, "remove", side_effect=delayed_cleanup), patch.object(accounts, "add_account", side_effect=observed_add):
            deleter, deleted = self.start_api("POST", "/api/accounts/delete", {"username": USER, "new_device": True})
            adder = None
            try:
                self.assertTrue(cleanup_entered.wait(4), "Deletion never reached cache cleanup")
                adder, added = self.start_api("POST", "/api/accounts", account)
                self.assertTrue(add_entered.wait(4), "Concurrent re-add never reached its handler")
                # With the fix, re-add waits on the registry lock until cleanup ends.
                if cleanup_owns_registry[0]:
                    release_cleanup.set()
                    deleter.join(4)
                adder.join(4)
                self.assertFalse(adder.is_alive())
                self.assertEqual(added[0][0], 200, added)
                profiles.save_identity(USER, {"user_id": "111", "unique_id": USER})
                status, login = self.api("POST", "/api/login", {"username": USER})
                self.assertEqual(status, 200, login)
                self.assertTrue(login["identity_conflict"])
            finally:
                release_cleanup.set()
                deleter.join(4)
                if adder:
                    adder.join(4)
        self.assertFalse(deleter.is_alive())
        self.assertEqual(deleted[0][0], 200, deleted)
        self.assertTrue(accounts._exists(USER))
        self.assertEqual(client_session.state_file(USER).read_text(), "FOREIGN_FRESH")
        blocked = False
        try:
            cloud.delete_posts(USER, "", count="all")
        except remote.RemoteError as exc:
            blocked = exc.stop_account
        self.assertEqual(self.requests_at("/v2/posts/delete"), [], "Old deletion must not reopen destructive dispatch")
        self.assertTrue(blocked)
        self.assertTrue(profiles.identity_conflict(USER))
        with contextlib.closing(db.connect()) as conn:
            self.assertEqual(conn.execute("SELECT user_id, unique_id FROM profiles WHERE username = ?", (USER,)).fetchone(),
                             ("111", USER))

    def test_media_unicode_photo_video_duplicate_delete_and_keepalive(self):
        status, folder = self.api("POST", "/api/media", {"name": "QA 50% literal%20 # 🌷"})
        self.assertEqual(status, 200, folder)
        self.assertTrue(Path(folder["path"]).is_relative_to(self.root))
        output = io.BytesIO()
        Image.new("RGB", (64, 48), (50, 95, 150)).save(output, "JPEG")
        photo = output.getvalue()
        video = b"\0\0\0\x18ftypmp42SYNTHETIC_VIDEO_ONLY"
        if self.http.sock is None:
            self.http.connect()
        sock = self.http.sock
        for name, payload, expected_name in (("synthetic.jpg", photo, "synthetic.jpg"),
                                            ("synthetic.jpg", photo, "synthetic (2).jpg"),
                                            ("synthetic.mp4", video, "synthetic.mp4")):
            self.http.request("POST", "/api/slots/upload?" + urlencode({"folder": folder["path"], "name": name}),
                              payload, {"Content-Type": "application/octet-stream"})
            response = self.http.getresponse()
            uploaded = json.loads(response.read())
            self.assertEqual(response.status, 200)
            self.assertEqual(uploaded["name"], expected_name)
            self.assertEqual((Path(folder["path"]) / expected_name).read_bytes(), payload)
            self.assertIs(self.http.sock, sock)
        status, files = self.api("GET", "/api/media/files?" + urlencode({"name": folder["name"]}))
        self.assertEqual(status, 200)
        self.assertEqual(sorted(f["kind"] for f in files["files"]), ["photo", "photo", "video"])
        self.assertFalse(list(Path(folder["path"]).glob("*.part")))
        self.assertEqual(self.api("POST", "/api/media/remove-file", {"name": folder["name"], "file": "../outside.jpg"})[0], 400)
        status, _ = self.api("POST", "/api/media/remove-file", {"name": folder["name"], "file": "synthetic.jpg"})
        self.assertEqual(status, 200)
        self.assertFalse((Path(folder["path"]) / "synthetic.jpg").exists())
        status, cleared = self.api("POST", "/api/media/clear", {"name": folder["name"]})
        self.assertEqual((status, cleared["removed"]), (200, 2))
        self.assertEqual(list(Path(folder["path"]).iterdir()), [])
        self.assertEqual(self.api("POST", "/api/media/delete", {"name": folder["name"]})[0], 200)
        self.assertFalse(Path(folder["path"]).exists())

    def test_untransferred_claims_return_and_concurrent_claims_are_unique(self):
        folder = self.root / "synthetic-claims"
        folder.mkdir()
        originals = []
        for n in range(8):
            path = folder / f"{n:02}.jpg"
            path.write_bytes(b"SYNTHETIC_ORIGINAL")
            originals.append(path)
        claimed, failures = [], []

        def take():
            try:
                claimed.extend(photo_source.hold_slot_photos([folder]))
            except Exception as error:
                failures.append(error)

        threads = [threading.Thread(target=take) for _ in originals]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(3)
            self.assertFalse(thread.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(len(set(claimed)), len(originals))
        self.assertEqual(photo_source.list_slot_photos(folder), [])
        self.assertEqual(photo_source.return_held(claimed), len(originals))
        self.assertEqual(set(photo_source.list_slot_photos(folder)), set(originals))
        self.assertFalse(list(folder.glob("*.claim_*")))

    def test_batch_preflight_failure_returns_all_claims_and_sends_no_media(self):
        state = client_session.state_file(USER)
        state.write_text("SYNTHETIC_KEPT")
        config.update({"uniq": {"enabled": False}})
        files = []
        for n in range(2):
            file = self.root / f"synthetic-{n}.jpg"
            Image.new("RGB", (32, 32), (30 + n, 70, 120)).save(file, "JPEG")
            files.append(file)
        originals = {file: file.read_bytes() for file in files}
        self.upstream.respond = lambda *a: (503, {"detail": "synthetic metadata unavailable"}, {"Retry-After": "1"})
        with self.assertRaises(photo_source.PhotoConsumeError):
            photo_source.prepare_post_photos(files, username=USER, via=(USER, ""))
        self.assertEqual(len(self.requests_at("/v1/photos/upload")), 1)
        self.assertFalse(any("/storage/" in r["path"] for r in self.upstream.seen))
        self.assertEqual({file: file.read_bytes() for file in files}, originals)
        self.assertFalse(list(self.root.glob("*.claim_*")))
        self.assertEqual(state.read_text(), "SYNTHETIC_KEPT")

    def test_partial_media_refusal_burns_only_dispatched_photo_without_retry(self):
        state = client_session.state_file(USER)
        state.write_text("SYNTHETIC_KEPT")
        config.update({"uniq": {"enabled": False}})
        files = []
        for n in range(2):
            file = self.root / f"synthetic-{n}.jpg"
            Image.new("RGB", (32, 32), (30 + n, 70, 120)).save(file, "JPEG")
            files.append(file)
        original_second = files[1].read_bytes()

        def respond(method, path, body):
            if path == "/v1/photos/upload":
                self.assertEqual(len(body["sizes"]), 2)
                return 200, {"state": "SYNTHETIC_AFTER_PREPARE", "state_saved": True, "ticket": "SYNTHETIC_TICKET",
                    "slots": [{"url": self.base + f"/storage/{n}", "auth": "SYNTHETIC_UPLOAD_AUTH", "user_id": "123"} for n in range(2)]}, {}
            cors = {"Access-Control-Allow-Origin": "https://www.tiktok.com"}
            if method == "OPTIONS":
                return 200, {}, {**cors, "Access-Control-Allow-Methods": "POST", "Access-Control-Allow-Headers": "authorization,content-crc32,content-disposition,content-type,x-storage-u"}
            self.assertEqual(path, "/storage/0", "Refused first transfer must not dispatch second")
            self.assertTrue(body.startswith(b"\xff\xd8"))
            return 403, {"message": "synthetic platform refusal"}, cors

        self.upstream.respond = respond
        with self.assertRaises(photo_source.PhotoConsumeError) as error:
            photo_source.prepare_post_photos(files, username=USER, via=(USER, ""))
        self.assertTrue(error.exception.stop_account)
        self.assertFalse(files[0].exists())
        self.assertEqual(files[1].read_bytes(), original_second)
        self.assertFalse(list(self.root.glob("*.claim_*")))
        self.assertEqual(len([r for r in self.requests_at("/storage/0") if r["method"] == "POST"]), 1)
        self.assertEqual(self.requests_at("/storage/1"), [])
        self.assertFalse(any(r["path"].endswith("/publish") for r in self.upstream.seen))
        self.assertEqual(state.read_text(), "SYNTHETIC_AFTER_PREPARE")

    def test_country_probe_parses_real_http_and_persists_country_without_old_profiles_regex(self):
        previous = proxy_pool.COUNTRY_URL
        proxy_pool.COUNTRY_URL = self.base + "/country"
        self.stack.callback(setattr, proxy_pool, "COUNTRY_URL", previous)
        self.upstream.respond = lambda *a: (200, {"region": "DE"}, {})
        # TTL-only tests mock the probe and cannot notice a removed parser import.
        code = proxy_pool._maybe_refresh_country(self.base, None)
        self.assertEqual(code, "DE")
        country_key = proxy_pool._country_key(self.base)
        self.assertEqual(config.get("proxy_countries")[country_key]["code"], "DE")
        self.assertEqual(len(self.requests_at("/country")), 1)
        self.assertEqual(proxy_pool._maybe_refresh_country(self.base, None), "DE")
        self.assertEqual(len(self.requests_at("/country")), 1, "Fresh country must not send a second GET")

    def test_email_profile_readback_and_refresh_keep_alias_uid_and_registry_ownership(self):
        alias = "fixture@example.invalid"
        accounts.add_account({"username": alias, "password": "Synthetic-password"})
        registry = (self.root / "accounts.json").read_bytes()
        client_session.state_file(alias).write_text("SYNTHETIC_ALIAS_STATE")
        config.update({"proxy_enabled": True, "proxies": [self.base], "proxies_login": [self.base]})

        def respond(method, path, body):
            if path.endswith("/profile/info"):
                return 200, {"state": "SYNTHETIC_ALIAS_STATE", "data": {"verdict": "observed", "before": {
                    "user_id": "123", "unique_id": "actual.qa", "nickname": "Synthetic 🌷"}, "policies": {}}}, {}
            self.assertEqual(path, "/v1/profiles")
            self.assertEqual(body["usernames"], ["actual.qa"], "Refresh must send a platform handle, not an email alias")
            return 200, {"profiles": [{"username": "actual.qa", "profile": {"method": "detail", "user_id": "123",
                "unique_id": "actual.qa", "nickname": "Synthetic refreshed", "followers": 42}, "posts": [], "avatar_url": None}], "failed": []}, {}

        self.upstream.respond = respond
        status, info = self.api("POST", "/api/tiktok-profile/info", {"username": alias})
        self.assertEqual(status, 200, info)
        self.assertEqual(profiles.get(alias)["user_id"], "123")
        status, result = self.api("POST", "/api/profiles/fetch", {"usernames": [alias], "posts": True})
        self.assertEqual(status, 200, result)
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["profiles"][0]["username"], alias)
        cached = profiles.get(alias)
        self.assertEqual((cached["user_id"], cached["unique_id"], cached["followers"]), ("123", "actual.qa", 42))
        self.assertIsNone(profiles.get("actual.qa"))
        self.assertEqual((self.root / "accounts.json").read_bytes(), registry)
        self.assertEqual(client_session.state_file(alias).read_text(), "SYNTHETIC_ALIAS_STATE")
        self.assertFalse(any(r["path"].endswith("/login") for r in self.upstream.seen))

    def test_registration_receipt_and_http_cancel_never_save_or_resend_mailbox_secret(self):
        from modules import registration
        job_id = "a" * 32
        phase = {"status": "queued"}

        def respond(method, path, body):
            if path == "/v1/register/capabilities":
                return 200, {"modes": [{"mode": 4, "supported": True, "available": True}]}, {}
            if path == "/v1/register":
                self.assertEqual(body["anymessage_token"], "Synthetic-mail-token")
                return 202, {"job_id": job_id, "mode": 4}, {}
            if path.endswith("/cancel"):
                phase["status"] = "cancelled"
            return 200, {"status": phase["status"], "retriable": False}, {}

        self.upstream.respond = respond
        status, started = self.api("POST", "/api/registration", {"mode": 4, "country": "US", "proxy": self.base,
                                                               "anymessage_token": "Synthetic-mail-token"})
        self.assertEqual(status, 200, started)
        self.assertEqual(started["status"], "queued")
        self.assertEqual(self.api("POST", "/api/registration", {"mode": 4, "country": "US", "proxy": self.base,
                                                               "anymessage_token": "Synthetic-mail-token"})[0], 400)
        self.assertEqual(len(self.requests_at("/v1/register")), 1)
        self.assertEqual(self.api("POST", "/api/registration/cancel", {})[1]["status"], "cancelled")
        self.assertEqual(len(self.requests_at(f"/v1/register/{job_id}/cancel")), 1)
        for file in (self.root / "registration").glob("*.json"):
            self.assertNotIn("Synthetic-mail-token", file.read_text())
        self.assertEqual(registration.status()["status"], "cancelled")


def run_checks():
    global ROOT, RUNTIME, main, Image, ClientServer
    global accounts, client_device, client_session, cloud, config, paths, photo_source, profile_edit, profiles, proxy_pool, remote

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-root", type=Path, default=ROOT)
    args, tests = parser.parse_known_args()
    ROOT = args.client_root.resolve()
    if not (ROOT / "modules/cloud.py").is_file():
        parser.error("--client-root must contain the standalone client")

    with contextlib.ExitStack() as isolation:
        RUNTIME = Path(isolation.enter_context(tempfile.TemporaryDirectory(prefix="nimbus-http-contract-"))).resolve()
        if RUNTIME.is_relative_to(ROOT):
            raise RuntimeError("Choose TMPDIR outside the checkout for HTTP checks")
        previous_env = os.environ.copy()
        isolation.callback(lambda: (os.environ.clear(), os.environ.update(previous_env)))
        os.environ.update(NIMBUS_DATA_ROOT=str(RUNTIME), NIMBUS_SERVER="", TIKTOK_BROWSER_PROFILE="chrome152",
                          HOME=str(RUNTIME), USERPROFILE=str(RUNTIME), XDG_CONFIG_HOME=str(RUNTIME / "config"),
                          XDG_CACHE_HOME=str(RUNTIME / "cache"), XDG_DATA_HOME=str(RUNTIME / "data"),
                          TMPDIR=str(RUNTIME), TEMP=str(RUNTIME), TMP=str(RUNTIME), PYTHONDONTWRITEBYTECODE="1",
                          HTTP_PROXY="", HTTPS_PROXY="", ALL_PROXY="", NO_PROXY="127.0.0.1,localhost,::1",
                          http_proxy="", https_proxy="", all_proxy="", no_proxy="127.0.0.1,localhost,::1")
        previous_tmp, previous_bytecode = tempfile.tempdir, sys.dont_write_bytecode
        tempfile.tempdir, sys.dont_write_bytecode = str(RUNTIME), True
        isolation.callback(setattr, tempfile, "tempdir", previous_tmp)
        isolation.callback(setattr, sys, "dont_write_bytecode", previous_bytecode)
        sys.path.insert(0, str(ROOT))
        isolation.callback(sys.path.remove, str(ROOT))

        for name in ("connect", "connect_ex"):
            original = getattr(socket.socket, name)

            def loopback(self, address, original=original):
                if self.family in (socket.AF_INET, socket.AF_INET6) and address[0] not in ("127.0.0.1", "::1", "localhost"):
                    raise AssertionError("HTTP checks refused an external socket")
                return original(self, address)

            setattr(socket.socket, name, loopback)
            isolation.callback(setattr, socket.socket, name, original)

        from curl_cffi import requests
        original_http = requests.Session.request

        def loopback_http(self, method, url, *args, **kwargs):
            if urlsplit(url).hostname not in ("127.0.0.1", "localhost", "::1"):
                raise AssertionError("HTTP checks refused external curl HTTP")
            return original_http(self, method, url, *args, **kwargs)

        requests.Session.request = loopback_http
        isolation.callback(setattr, requests.Session, "request", original_http)
        from PIL import Image
        import main
        from modules import accounts, client_device, client_session, cloud, config, paths, photo_source, profile_edit, profiles, proxy_pool, remote

        proxy_pool._maintenance_pause.set()
        isolation.callback(proxy_pool._maintenance_pause.clear)

        class ContextServer(main._QuietThreadingHTTPServer):
            def finish_request(self, request, address):
                # HTTP worker threads do not inherit the caller's ContextVars.
                with paths.use_root(self.data_root):
                    super().finish_request(request, address)

        ClientServer = ContextServer
        result = unittest.main(argv=[sys.argv[0], *tests], verbosity=2, exit=False)
        return 0 if result.result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(run_checks())
