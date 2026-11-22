"""Confirmed account identity goes to SQLite, not the credential/session key."""
import contextlib
import ast
import itertools
import json
from pathlib import Path
import socket
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from modules import accounts, avatars, campaign, client_device, client_session, cloud, config, db, eventlog, paths, profiles, remote, signin


class LoginProfileTests(unittest.TestCase):
    def setUp(self):
        stack = self.stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        stack.callback(self.close_fixture_log)
        stack.enter_context(paths.use_root(self.root))
        stack.enter_context(client_device.use_browser_profile("chrome152"))
        stack.enter_context(patch.object(config, "get", side_effect=lambda key, default=None: default))
        stack.enter_context(patch.object(client_session, "sticky_proxy", side_effect=lambda proxy, name: proxy))
        stack.enter_context(patch.object(socket.socket, "connect", side_effect=AssertionError("network denied")))
        stack.enter_context(patch.object(remote.requests.Session, "request", side_effect=AssertionError("HTTP denied")))
        self.alias = "fixture@example.invalid"
        accounts.add_accounts_bulk(self.alias + ":synthetic-password")
        self.identity = {"user_id": "1000000000000000001", "unique_id": "real.profile",
                         "sec_uid": "synthetic-sec", "nickname": "Весна 🌷"}

    def close_fixture_log(self):
        with eventlog._file_lock:
            if eventlog._file_handler_path == self.root / 'logs/events.log':
                if eventlog._file_handler is not None:
                    eventlog._file_handler.close()
                eventlog._file_handler = eventlog._file_handler_path = None

    def test_email_login_saves_confirmed_identity_without_renaming_account(self):
        before = (self.root / "accounts.json").read_bytes()
        response = {"ok": True, "verdict": "ok", "state_saved": True,
                    "state": "confirmed-state", "profile": {**self.identity, "password": "must-not-store"}}
        with patch.object(remote, "request", return_value=response) as request:
            result = cloud.login(accounts.load_account(self.alias), "http://fixture.invalid")
        self.assertTrue(result["ok"])
        stored = profiles.get(self.alias)
        self.assertIsNotNone(stored)
        for field, value in self.identity.items():
            self.assertEqual(stored[field], value)
        self.assertIsNone(stored["followers"])
        self.assertEqual((self.root / "accounts.json").read_bytes(), before)
        self.assertEqual(cloud.state_file(self.alias).read_text(), "confirmed-state")
        self.assertFalse(cloud.state_file("real.profile").exists())
        self.assertNotIn(b"must-not-store", paths.here(db.DB_FILE).read_bytes())
        request.assert_called_once()
        self.assertEqual(request.call_args.kwargs["json"]["username"], self.alias)
        self.assertEqual(accounts.list_accounts()[0]["profile"]["unique_id"], "real.profile")

    def test_fixture_cleanup_closes_its_log_before_removing_data(self):
        eventlog.say('Synthetic fixture log')
        handler = eventlog._file_handler
        self.assertIsNotNone(handler.stream)
        self.stack.close()
        self.assertIsNone(handler.stream)
        self.assertFalse(self.root.exists())

    def test_failed_cache_deletion_keeps_uid_quarantine(self):
        profiles.save_identity(self.alias, self.identity)
        profiles.mark_identity_conflict(self.alias)
        with patch.object(db, "connect", side_effect=profiles.sqlite3.OperationalError("fixture deletion failure")):
            self.assertIs(avatars.remove(self.alias), False)
        self.assertTrue(profiles.identity_conflict(self.alias))
        self.assertTrue(profiles.get(self.alias)["identity_conflict"])

    def test_captured_quarantine_reset_does_not_remove_a_newer_marker(self):
        profiles.save_identity(self.alias, self.identity)
        profiles.mark_identity_conflict(self.alias)
        deleted_marker = profiles.identity_conflict_marker(self.alias)
        profiles.mark_identity_conflict(self.alias)
        profiles.forget_identity_conflict(self.alias, deleted_marker)
        with patch.object(db, "connect", side_effect=AssertionError("The new in-memory marker must remain")):
            self.assertTrue(profiles.identity_conflict(self.alias))

    def test_failed_session_deletion_keeps_registered_account_quarantined(self):
        profiles.save_identity(self.alias, self.identity)
        profiles.mark_identity_conflict(self.alias)
        with patch.object(client_session, "clear_session", side_effect=OSError("fixture deletion failure")):
            with self.assertRaises(OSError):
                accounts.remove_account(self.alias, new_device=True)
        self.assertTrue(accounts._exists(self.alias))
        self.assertTrue(profiles.identity_conflict(self.alias))

    def test_malformed_identity_is_not_merged_into_existing_cache(self):
        profiles.save_identity(self.alias, self.identity)
        before = profiles.get(self.alias)
        for invalid in ({}, [], "handle", 7, False,
                        {**self.identity, "user_id": "01"},
                        {**self.identity, "user_id": "0"},
                        {**self.identity, "user_id": "1" * 65},
                        {**self.identity, "user_id": 123},
                        {**self.identity, "unique_id": "other/handle"},
                        {**self.identity, "unique_id": "handle\n"},
                        {**self.identity, "nickname": []},
                        {**self.identity, "sec_uid": False}):
            with self.subTest(invalid=invalid), patch.object(remote, "request", return_value={
                    "ok": True, "state": "confirmed-state", "profile": invalid}) as request:
                result = cloud.login(accounts.load_account(self.alias), "http://fixture.invalid")
                self.assertTrue(result["ok"])
                self.assertIs(result.get("profile_saved"), False)
                self.assertEqual(profiles.get(self.alias), before)
                request.assert_called_once()

    def test_conflicting_uid_does_not_mix_identity_with_another_accounts_cache(self):
        profiles.save_identity(self.alias, self.identity)
        profiles.save_posts(self.alias, [{"id": "5001", "desc": "kept post"}])
        with contextlib.closing(db.connect()) as conn:
            before = conn.execute("SELECT user_id, unique_id, nickname FROM profiles WHERE username = ?", (self.alias,)).fetchone()
        response = {"ok": True, "state": "confirmed-state",
                    "profile": {**self.identity, "user_id": "999", "unique_id": "other.account"}}
        with patch.object(remote, "request", return_value=response) as request:
            result = cloud.login(accounts.load_account(self.alias), "http://fixture.invalid")
        self.assertTrue(result["ok"])
        self.assertFalse(result["profile_saved"])
        self.assertTrue(result.get("identity_conflict"))
        self.assertTrue(result.get("stop_account"))
        self.assertFalse(result.get("retriable", True))
        self.assertIn("UID", result.get("warning", ""))
        visible = accounts.list_accounts()[0]["profile"]
        self.assertTrue(visible.get("identity_conflict"))
        self.assertIsNone(visible.get("unique_id"))
        self.assertIsNone(visible.get("nickname"))
        with contextlib.closing(db.connect()) as conn:
            self.assertEqual(conn.execute("SELECT user_id, unique_id, nickname FROM profiles WHERE username = ?", (self.alias,)).fetchone(), before)
            self.assertEqual(conn.execute("SELECT item_id FROM posts WHERE username = ?", (self.alias,)).fetchall(), [("5001",)])
        self.assertEqual(cloud.state_file(self.alias).read_text(), "confirmed-state")
        request.assert_called_once()

    def test_sparse_login_preserves_statistics_posts_and_refresh_metadata(self):
        profiles.save_row(self.alias, {**self.identity, "method": "ssr", "signature": "kept",
                                      "followers": 42, "following": 7, "likes": 99,
                                      "verified": 1, "private_account": 0, "language": "ru"})
        profiles.save_posts(self.alias, [{"id": "5001", "desc": "kept post",
                                         "stats": {"playCount": 17}}], {"5001": True})
        before, posts = profiles.get(self.alias), profiles.posts_of(self.alias)
        sparse = {"user_id": self.identity["user_id"], "unique_id": "new.handle",
                  "nickname": None, "sec_uid": None, "posts": [], "followers": 0}
        with patch.object(remote, "request", return_value={"ok": True, "state": "confirmed-state",
                                                            "profile": sparse}):
            self.assertTrue(cloud.login(accounts.load_account(self.alias), "")["profile_saved"])
        after = profiles.get(self.alias)
        self.assertEqual(after, {**before, "unique_id": "new.handle"})
        self.assertEqual(profiles.posts_of(self.alias), [
            {**post, "url": post["url"].replace("real.profile", "new.handle")} for post in posts])

    def test_legacy_login_does_not_clear_existing_profile(self):
        profiles.save_identity(self.alias, self.identity)
        before = profiles.get(self.alias)
        for payload in ({}, {"profile": None}):
            with self.subTest(payload=payload), patch.object(remote, "request", return_value={
                    "ok": True, "state": "confirmed-state", **payload}):
                self.assertTrue(cloud.login(accounts.load_account(self.alias), "")["ok"])
                self.assertEqual(profiles.get(self.alias), before)

    def test_unconfirmed_login_never_saves_response_identity(self):
        profiles.save_identity(self.alias, self.identity)
        before = profiles.get(self.alias)
        auth = cloud.state_file(self.alias)
        auth.write_text("kept-state")
        for response in (None, [], {"ok": "true"}, {"ok": True, "verdict": "unknown"},
                         {"ok": False, "verdict": "unknown"}, {"ok": False, "verdict": "rejected"},
                         {"ok": True, "state_saved": False}, {"ok": True, "state": " "}):
            if isinstance(response, dict):
                response = {"state": "replacement", "profile": {**self.identity, "unique_id": "not.confirmed"},
                            **response}
            with self.subTest(response=response), patch.object(remote, "request", return_value=response) as request:
                result = cloud.login(accounts.load_account(self.alias), "")
                self.assertFalse(result["ok"])
                self.assertEqual(profiles.get(self.alias), before)
                request.assert_called_once()

    def test_local_state_save_failure_does_not_cache_identity(self):
        auth = cloud.state_file(self.alias)
        auth.write_text("kept-state")
        for failure in (False, OSError("fixture disk full")):
            kwargs = {"side_effect": failure} if isinstance(failure, OSError) else {"return_value": failure}
            with self.subTest(failure=failure), patch.object(remote, "request", return_value={
                    "ok": True, "state": "replacement", "profile": self.identity}) as request, \
                    patch.object(client_session, "complete_login_if_current", **kwargs):
                result = cloud.login(accounts.load_account(self.alias), "")
                self.assertFalse(result["ok"])
                self.assertFalse(result["retriable"])
                self.assertIsNone(profiles.get(self.alias))
                self.assertEqual(auth.read_text(), "kept-state")
                request.assert_called_once()

    def test_cache_failure_does_not_replay_or_fail_confirmed_login(self):
        with patch.object(remote, "request", return_value={"ok": True, "state": "confirmed-state",
                                                            "profile": self.identity}) as request, \
                patch.object(profiles, "save_identity", side_effect=profiles.sqlite3.OperationalError("fixture disk")), \
                patch.object(signin.proxy_pool, "report_ok"), patch.object(signin.proxy_pool, "report_fail") as failed:
            self.assertTrue(signin.attempt_via_server(accounts.load_account(self.alias), "", self.alias))
        self.assertEqual(cloud.state_file(self.alias).read_text(), "confirmed-state")
        request.assert_called_once()
        failed.assert_not_called()

    def test_sequential_email_logins_keep_each_alias_state_and_identity_isolated(self):
        other = "other@example.invalid"
        accounts.add_accounts_bulk(other + ":another-synthetic-password")
        before = paths.here(accounts.ACCOUNTS_FILE).read_bytes()
        identities = [self.identity, {"user_id": "2000000000000000002", "unique_id": "other.handle"}]
        with patch.object(remote, "request", side_effect=[
                {"ok": True, "state": "state-one", "profile": identities[0]},
                {"ok": True, "state": "state-two", "profile": identities[1]}]) as request:
            for alias, identity in zip((self.alias, other), identities):
                self.assertTrue(cloud.login(accounts.load_account(alias), "")["ok"])
                self.assertEqual(profiles.get(alias)["user_id"], identity["user_id"])
                self.assertEqual(profiles.get(alias)["unique_id"], identity["unique_id"])
        self.assertEqual(cloud.state_file(self.alias).read_text(), "state-one")
        self.assertEqual(cloud.state_file(other).read_text(), "state-two")
        self.assertEqual(paths.here(accounts.ACCOUNTS_FILE).read_bytes(), before)
        self.assertEqual([call.kwargs["json"]["username"] for call in request.call_args_list], [self.alias, other])
        self.assertFalse(cloud.state_file("real.profile").exists())
        self.assertFalse(cloud.state_file("other.handle").exists())

    def test_refresh_requests_real_handle_and_saves_all_results_under_login_alias(self):
        profiles.save_identity(self.alias, self.identity)
        row = {**self.identity, "username": "real.profile", "method": "ssr", "followers": 42}
        posts = [{"item_id": "5001", "views": 17, "shadow": True}]
        response = {"profiles": [{"username": "real.profile", "profile": row,
                                  "posts": posts, "avatar_url": "https://fixture.invalid/avatar.png"}],
                    "failed": []}
        with patch.object(profiles, "anon_proxy", return_value="http://fixture.invalid"), \
                patch.object(cloud, "profiles", return_value=response) as request, \
                patch.object(cloud, "session_check") as check, \
                patch.object(profiles, "_avatar_via") as avatar:
            try:
                result = profiles.fetch_now([self.alias])
            except profiles.ProfileInputError as exc:
                self.fail(f"an existing email login must be refreshable: {exc}")
        self.assertEqual(request.call_args.args[0], ["real.profile"])
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["profiles"][0]["username"], self.alias)
        self.assertEqual(profiles.get(self.alias)["followers"], 42)
        self.assertEqual(profiles.posts_of(self.alias)[0]["item_id"], "5001")
        self.assertIsNone(profiles.get("real.profile"))
        self.assertEqual(profiles.posts_of("real.profile"), [])
        avatar.assert_called_once_with(self.alias, response["profiles"][0]["avatar_url"], "http://fixture.invalid")
        check.assert_not_called()

    def test_user_refresh_resolves_an_existing_email_session_once_without_login(self):
        auth = cloud.state_file(self.alias)
        auth.write_text("kept-state")
        response = {"profiles": [{"username": "real.profile", "profile": {**self.identity, "method": "ssr"},
                                  "posts": None, "avatar_url": ""}], "failed": []}
        with patch.object(profiles, "anon_proxy", return_value="http://fixture.invalid"), \
                patch.object(remote, "request", return_value={
                    "data": {"alive": True, "uid": self.identity["user_id"], "username": "real.profile"},
                    "state": "checked-state"}) as check, \
                patch.object(cloud, "profiles", return_value=response) as public, \
                patch.object(cloud, "login") as login:
            accounts.list_accounts()
            check.assert_not_called()
            first = profiles.fetch_now([self.alias])
            second = profiles.fetch_now([self.alias])
        self.assertEqual(first["failed"], [])
        self.assertEqual(second["failed"], [])
        self.assertEqual(public.call_args.args[0], ["real.profile"])
        self.assertEqual(profiles.get(self.alias)["user_id"], self.identity["user_id"])
        self.assertEqual(auth.read_text(), "checked-state")
        check.assert_called_once()
        self.assertEqual(check.call_args.args[1], "/v1/session/check")
        self.assertEqual(check.call_args.kwargs["json"]["username"], self.alias)
        login.assert_not_called()

    def test_refresh_rejects_wrong_uid_without_overwriting_cache(self):
        profiles.save_identity(self.alias, self.identity)
        profiles.save_posts(self.alias, [{"id": "5001", "desc": "kept post"}])
        before, posts = profiles.get(self.alias), profiles.posts_of(self.alias)
        response = {"profiles": [{"username": "real.profile", "profile": {
            "user_id": "999", "unique_id": "real.profile", "method": "ssr", "followers": 999},
            "posts": [], "avatar_url": "https://fixture.invalid/wrong.png"}], "failed": []}
        with patch.object(profiles, "anon_proxy", return_value="http://fixture.invalid"), \
                patch.object(cloud, "profiles", return_value=response), \
                patch.object(profiles, "_avatar_via") as avatar:
            result = profiles.fetch_now([self.alias])
        self.assertEqual([f["username"] for f in result["failed"]], [self.alias])
        self.assertEqual(result["profiles"], [])
        self.assertEqual(profiles.get(self.alias), before)
        self.assertEqual(profiles.posts_of(self.alias), posts)
        avatar.assert_not_called()

    def test_same_handle_aliases_share_one_request_but_keep_separate_cached_posts(self):
        other = "other@example.invalid"
        accounts.add_accounts_bulk(other + ":synthetic-password")
        profiles.save_identity(self.alias, self.identity)
        profiles.save_identity(other, self.identity)
        response = {"profiles": [{"username": "REAL.PROFILE", "profile": {**self.identity, "method": "ssr"},
                                  "posts": [{"item_id": "5001", "views": 17, "shadow": True}],
                                  "avatar_url": "https://fixture.invalid/avatar.png"}], "failed": []}
        started, finished = [], []
        with patch.object(profiles, "anon_proxy", return_value="http://fixture.invalid"), \
                patch.object(cloud, "profiles", return_value=response) as request, \
                patch.object(profiles, "_avatar_via") as avatar:
            profiles._run_batch([self.alias, other], "ssr", True,
                                started.append, lambda name, reason: finished.append((name, reason)))
        request.assert_called_once()
        self.assertEqual(request.call_args.args[0], ["real.profile"])
        self.assertEqual(started, [self.alias, other])
        self.assertEqual(finished, [(self.alias, ""), (other, "")])
        self.assertEqual([call.args[0] for call in avatar.call_args_list], [self.alias, other])
        for alias in (self.alias, other):
            self.assertEqual(profiles.get(alias)["posts"]["views"], 17)
            self.assertEqual(profiles.posts_of(alias)[0]["item_id"], "5001")
        profiles.save_shadows(self.alias, {"5001": False})
        self.assertFalse(profiles.posts_of(self.alias)[0]["shadow"])
        self.assertTrue(profiles.posts_of(other)[0]["shadow"])
        avatars.rename(self.alias, "renamed@example.invalid")
        self.assertEqual(profiles.posts_of("renamed@example.invalid")[0]["item_id"], "5001")
        profiles.forget_recent("renamed@example.invalid", 1)
        self.assertEqual(profiles.posts_of("renamed@example.invalid"), [])
        self.assertEqual(profiles.posts_of(other)[0]["item_id"], "5001")

    def test_cached_post_links_use_real_handle_not_email_login(self):
        profiles.save_identity(self.alias, self.identity)
        profiles.save_posts(self.alias, [{"id": "5001", "desc": "synthetic"}])
        self.assertEqual(profiles.posts_of(self.alias)[0]["url"],
                         "https://www.tiktok.com/@real.profile/video/5001")

    def test_refresh_resolution_rejects_unknown_or_malformed_owner_without_public_request(self):
        cloud.state_file(self.alias).write_text("kept-state")
        replies = ({"alive": False, "verdict": "unknown", "error": "fixture unknown"},
                   {"alive": True, "uid": "123", "username": "wrong/name"},
                   {"alive": True, "uid": "01", "username": "real.profile"},
                   {"alive": True, "uid": False, "username": "real.profile"},
                   {"alive": True, "uid": "123", "username": "real.profile", "stop_account": True})
        for reply in replies:
            with self.subTest(reply=reply), patch.object(profiles, "anon_proxy", return_value="http://fixture.invalid"), \
                    patch.object(cloud, "session_check", return_value=reply) as check, \
                    patch.object(cloud, "profiles") as public, patch.object(cloud, "login") as login:
                result = profiles.fetch_now([self.alias])
                self.assertEqual(result["profiles"], [])
                self.assertEqual([f["username"] for f in result["failed"]], [self.alias])
                self.assertIsNone(profiles.get(self.alias))
                check.assert_called_once()
                public.assert_not_called()
                login.assert_not_called()

    def test_refresh_input_rejects_unknown_email_and_paths_without_requests(self):
        for name in ("unknown@example.invalid", "../fixture@example.invalid", "fixture/other@example.invalid",
                     "fixture\\other@example.invalid", "fixture\x00@example.invalid", "bad+handle", "handle\nother"):
            with self.subTest(name=name), patch.object(cloud, "session_check") as check, \
                    patch.object(cloud, "profiles") as public:
                with self.assertRaises(profiles.ProfileInputError):
                    profiles.fetch_now([name])
                check.assert_not_called()
                public.assert_not_called()

    def test_refresh_failures_and_missing_responses_finish_original_alias_callbacks(self):
        profiles.save_identity(self.alias, self.identity)
        before = profiles.get(self.alias)
        for response in ({"profiles": [], "failed": [{"username": "REAL.PROFILE", "reason": "fixture refused"}]},
                         {"profiles": [], "failed": []}):
            started, done = [], []
            with self.subTest(response=response), patch.object(profiles, "anon_proxy", return_value="http://fixture.invalid"), \
                    patch.object(cloud, "profiles", return_value=response):
                profiles._run_batch([self.alias], "ssr", True, started.append,
                                    lambda alias, reason: done.append((alias, reason)))
                self.assertEqual(started, [self.alias])
                self.assertEqual([alias for alias, _ in done], [self.alias])
                self.assertTrue(done[0][1])
                self.assertEqual(profiles.get(self.alias), before)

    def test_readding_a_renamed_alias_cannot_steal_its_namespaced_posts(self):
        row = [{"item_id": "5001", "views": 17}]
        for alias in (self.alias, "other@example.invalid"):
            profiles.save_identity(alias, self.identity)
            profiles.save_post_rows(alias, row)
        avatars.rename("other@example.invalid", "renamed@example.invalid")
        profiles.save_identity("other@example.invalid", self.identity)
        profiles.save_post_rows("other@example.invalid", row)
        for alias in (self.alias, "other@example.invalid", "renamed@example.invalid"):
            self.assertEqual([p["item_id"] for p in profiles.posts_of(alias)], ["5001"])

    def test_malformed_profile_batch_is_reported_per_alias_without_cache_writes(self):
        profiles.save_identity(self.alias, self.identity)
        before = profiles.get(self.alias)
        for response in (None, {}, {"profiles": [], "failed": None},
                         {"profiles": [{"username": "real.profile", "profile": {**self.identity, "method": "ssr"},
                                        "posts": "malformed"}], "failed": []},
                         {"profiles": [{"username": "real.profile", "profile": {**self.identity, "method": "ssr", "not_a_column": "bad"},
                                        "posts": None, "avatar_url": ""}], "failed": []},
                         {"profiles": [{"username": "real.profile", "profile": {**self.identity, "method": "ssr"},
                                        "posts": [{"item_id": "5001", "views": {}}]}], "failed": []}):
            with self.subTest(response=response), patch.object(profiles, "anon_proxy", return_value="http://fixture.invalid"), \
                    patch.object(cloud, "profiles", return_value=response):
                try:
                    result = profiles.fetch_now([self.alias])
                except (KeyError, TypeError, AttributeError, profiles.sqlite3.Error) as exc:
                    self.fail(f"malformed profile response must finish its alias safely: {exc}")
                self.assertEqual([f["username"] for f in result["failed"]], [self.alias])
                self.assertEqual(profiles.get(self.alias), before)

    def test_identity_confirmed_during_refresh_is_checked_again_before_cache_write(self):
        profiles.save_row(self.alias, {"unique_id": "real.profile", "method": "ssr"})
        def response(*args):
            profiles.save_identity(self.alias, self.identity)
            return {"profiles": [{"username": "real.profile", "profile": {
                **self.identity, "user_id": "999", "method": "ssr"}, "posts": None, "avatar_url": ""}], "failed": []}
        with patch.object(profiles, "anon_proxy", return_value="http://fixture.invalid"), \
                patch.object(cloud, "profiles", side_effect=response):
            result = profiles.fetch_now([self.alias])
        self.assertEqual([f["username"] for f in result["failed"]], [self.alias])
        self.assertEqual(profiles.get(self.alias)["user_id"], self.identity["user_id"])

    def test_quarantined_session_cannot_dispatch_uploads_or_other_account_operations(self):
        profiles.save_identity(self.alias, self.identity)
        with patch.object(remote, "request", return_value={"ok": True, "state": "confirmed-state",
                "profile": {**self.identity, "user_id": "999", "unique_id": "other.account"}}):
            self.assertTrue(cloud.login(accounts.load_account(self.alias), "")["identity_conflict"])
        for endpoint in ("/v1/photos/upload", "/v1/photos/publish", "/v1/profile/update", "/v1/session/check"):
            with self.subTest(endpoint=endpoint), patch.object(remote, "request") as request:
                with self.assertRaises(remote.RemoteError) as caught:
                    cloud._call(self.alias, endpoint, {})
                self.assertTrue(caught.exception.stop_account)
                self.assertFalse(caught.exception.network)
                request.assert_not_called()
        self.assertEqual(profiles.posts_of(self.alias), [])

    def test_session_check_uid_mismatch_stops_before_campaign_can_skip_login(self):
        profiles.save_identity(self.alias, self.identity)
        cloud.state_file(self.alias).write_text("kept-state")
        with patch.object(remote, "request", return_value={"data": {
                "alive": True, "uid": "999", "username": "other.account"}, "state": "checked-state"}) as request:
            result = cloud.session_check(self.alias, "")
        self.assertTrue(result.get("identity_conflict"))
        self.assertTrue(result.get("stop_account"))
        self.assertFalse(result.get("network", False))
        self.assertTrue(accounts.list_accounts()[0]["profile"].get("identity_conflict"))
        self.assertEqual(cloud.state_file(self.alias).read_text(), "checked-state")
        request.assert_called_once()

    def test_confirmed_login_uid_conflict_warning_survives_signin_without_failure_or_ban(self):
        profiles.save_identity(self.alias, self.identity)
        response = {"ok": True, "state": "confirmed-state", "profile": {
            **self.identity, "user_id": "999", "unique_id": "other.account"}}
        with patch.object(remote, "request", return_value=response) as request, \
                patch.object(signin.proxy_pool, "report_ok"), patch.object(signin.eventlog, "say") as say:
            self.assertTrue(signin.run(self.alias, tee=False, proxy=""))
        try:
            flags = signin.last_warning()
        except AttributeError:
            self.fail("signin must retain confirmed-login warnings in thread-local state")
        self.assertTrue(flags.get("identity_conflict"))
        self.assertTrue(flags.get("stop_account"))
        self.assertFalse(flags.get("profile_saved", True))
        self.assertIn("UID", flags.get("warning", ""))
        self.assertFalse(signin.last_banned())
        self.assertIn("вход подтверждён", say.call_args.args[0].casefold())
        self.assertNotIn("не удался", say.call_args.args[0])
        request.assert_called_once()

    def test_campaign_pauses_after_confirmed_login_uid_conflict_before_notices_or_publish(self):
        profiles.save_identity(self.alias, self.identity)
        held = SimpleNamespace(url="", release=Mock())
        response = {"ok": True, "state": "confirmed-state", "profile": {
            **self.identity, "user_id": "999", "unique_id": "other.account"}}
        with patch.object(campaign, "_stop_requested", return_value=False), \
                patch.object(campaign, "_take_proxy", return_value=held), \
                patch.object(campaign, "_worker_set"), patch.object(campaign, "_worker_clear"), \
                patch.object(campaign, "_net_retry", return_value=({"alive": False, "stale": True}, False)), \
                patch.object(campaign, "_fail_account") as failed, patch.object(campaign, "_pause_account") as paused, \
                patch.object(campaign, "_read_notices") as notices, \
                patch.object(campaign.batch_publish, "BatchWorker", side_effect=AssertionError("must not publish")) as publish, \
                patch.object(signin.proxy_pool, "report_ok"), patch.object(remote, "request", return_value=response), \
                patch.object(signin, "run", side_effect=lambda name, tee=False: signin.attempt_via_server(accounts.load_account(name), "", name)):
            try:
                campaign._worker_run(accounts.load_account(self.alias), [], "", "", 0, 0, 1, None, itertools.count())
            except AssertionError as exc:
                self.fail(str(exc))
        paused.assert_called_once_with(self.alias)
        failed.assert_called_once()
        self.assertIn("UID", failed.call_args.args[1])
        self.assertNotIn("вход не удался", failed.call_args.args[1])
        notices.assert_not_called()
        publish.assert_not_called()
        held.release.assert_called_once()

    def test_manual_login_returns_confirmed_uid_conflict_warning_without_selecting_default(self):
        profiles.save_identity(self.alias, self.identity)
        tree = ast.parse((Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8"))
        method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_api_login")
        scope = {"config": config}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "main.py", "exec"), scope)
        received = []
        handler = SimpleNamespace(_read_json=lambda: ({"username": self.alias}, None),
                                  _campaign_running=lambda: False, _json=lambda body, *args: received.append(body))
        with patch.object(remote, "request", return_value={"ok": True, "state": "confirmed-state", "profile": {
                **self.identity, "user_id": "999", "unique_id": "other.account"}}), \
                patch.object(signin.proxy_pool, "report_ok"), patch.object(config, "update") as updated, \
                patch.object(signin, "run", side_effect=lambda name, tee=False: signin.attempt_via_server(accounts.load_account(name), "", name)):
            scope["_api_login"](handler)
        self.assertTrue(received[0]["ok"])
        self.assertTrue(received[0].get("identity_conflict"))
        self.assertTrue(received[0].get("stop_account"))
        self.assertFalse(received[0].get("profile_saved", True))
        self.assertIn("UID", received[0].get("warning", ""))
        self.assertNotIn("banned", received[0])
        updated.assert_not_called()

    def test_profile_and_returned_posts_are_written_in_one_uid_checked_transaction(self):
        profiles.save_identity(self.alias, self.identity)
        response = {"profiles": [{"username": "real.profile", "profile": {**self.identity, "method": "ssr"},
                                  "posts": [{"item_id": "5001", "views": 17}], "avatar_url": ""}], "failed": []}
        save_posts = profiles.save_post_rows
        def interleaved(name, rows, shadows=None, conn=None):
            self.assertIsNotNone(conn, "profile and posts must share a SQLite transaction")
            self.assertTrue(conn.in_transaction)
            with contextlib.closing(db.connect()) as other:
                other.execute("PRAGMA busy_timeout = 0")
                with self.assertRaises(profiles.sqlite3.OperationalError):
                    other.execute("UPDATE profiles SET user_id = '999' WHERE username = ?", (name,))
            return save_posts(name, rows, shadows, conn=conn)
        with patch.object(profiles, "anon_proxy", return_value="http://fixture.invalid"), \
                patch.object(cloud, "profiles", return_value=response), \
                patch.object(profiles, "save_post_rows", side_effect=interleaved):
            profiles.fetch_now([self.alias])
        self.assertEqual(profiles.get(self.alias)["user_id"], self.identity["user_id"])
        self.assertEqual(profiles.posts_of(self.alias)[0]["views"], 17)

    def test_mismatched_returned_handle_is_rejected_with_or_without_cached_uid(self):
        for cached_uid in (None, self.identity["user_id"]):
            with contextlib.closing(db.connect()) as conn:
                conn.execute("DELETE FROM profiles WHERE username = ?", (self.alias,))
                conn.commit()
            profiles.save_row(self.alias, {"method": "ssr", "unique_id": "real.profile", "user_id": cached_uid})
            before = profiles.get(self.alias)
            response = {"profiles": [{"username": "real.profile", "profile": {
                **self.identity, "unique_id": "wrong.handle", "method": "ssr"},
                "posts": [], "avatar_url": ""}], "failed": []}
            with self.subTest(cached_uid=cached_uid), patch.object(profiles, "anon_proxy", return_value="http://fixture.invalid"), \
                    patch.object(cloud, "profiles", return_value=response):
                result = profiles.fetch_now([self.alias])
                self.assertEqual([f["username"] for f in result["failed"]], [self.alias])
                self.assertEqual(profiles.get(self.alias), before)

    def test_sparse_post_rows_keep_metrics_in_either_order(self):
        profiles.save_identity(self.alias, self.identity)
        for posts in ([{"item_id": "5001"}, {"item_id": "5002", "views": 17}],
                      [{"item_id": "5002", "views": 17}, {"item_id": "5001"}]):
            response = {"profiles": [{"username": "real.profile", "profile": {**self.identity, "method": "ssr"},
                                      "posts": posts, "avatar_url": ""}], "failed": []}
            with self.subTest(posts=posts), patch.object(profiles, "anon_proxy", return_value="http://fixture.invalid"), \
                    patch.object(cloud, "profiles", return_value=response):
                try:
                    result = profiles.fetch_now([self.alias])
                except KeyError as exc:
                    self.fail(f"sparse post field ordering must not lose metrics or abort: {exc}")
                self.assertEqual(result["failed"], [])
                known = {row["item_id"]: row for row in profiles.posts_of(self.alias)}
                self.assertEqual(known["5002"]["views"], 17)
                self.assertIsNone(known["5001"]["views"])

    def test_post_write_failure_rolls_back_profile_and_finishes_remaining_alias_once(self):
        other = "other@example.invalid"
        profiles.save_identity(self.alias, self.identity)
        profiles.save_row(self.alias, {"user_id": self.identity["user_id"], "unique_id": "real.profile", "method": "ssr", "followers": 42})
        profiles.save_posts(self.alias, [{"id": "4001", "desc": "kept"}])
        profiles.save_identity(other, {**self.identity, "user_id": "999", "unique_id": "other.profile"})
        before, posts = profiles.get(self.alias), profiles.posts_of(self.alias)
        response = {"profiles": [
            {"username": "real.profile", "profile": {**self.identity, "method": "ssr", "followers": 77},
             "posts": [{"item_id": "5001"}], "avatar_url": ""},
            {"username": "other.profile", "profile": {**self.identity, "user_id": "999", "unique_id": "other.profile", "method": "ssr"},
             "posts": [{"item_id": "5002", "views": 17}], "avatar_url": ""}], "failed": []}
        save_posts = profiles.save_post_rows
        def write(name, rows, shadows=None, conn=None):
            if name == self.alias:
                raise profiles.sqlite3.OperationalError("fixture post write failed")
            return save_posts(name, rows, shadows, conn=conn)
        done = []
        with patch.object(profiles, "anon_proxy", return_value="http://fixture.invalid"), \
                patch.object(cloud, "profiles", return_value=response), patch.object(profiles, "save_post_rows", side_effect=write):
            profiles._run_batch([self.alias, other], "ssr", True, on_done=lambda name, error: done.append((name, error)))
        self.assertEqual([name for name, _ in done], [self.alias, other])
        self.assertTrue(done[0][1])
        self.assertEqual(done[1][1], "")
        self.assertEqual(profiles.get(self.alias), before)
        self.assertEqual(profiles.posts_of(self.alias), posts)
        self.assertEqual(profiles.posts_of(other)[0]["views"], 17)

    def test_invalid_unicode_identity_warns_after_one_confirmed_login_without_state_loss(self):
        profiles.save_identity(self.alias, self.identity)
        before = profiles.get(self.alias)
        for field in ("nickname", "sec_uid"):
            with self.subTest(field=field), patch.object(remote, "request", return_value={
                    "ok": True, "state": "confirmed-state", "profile": {**self.identity, field: "\ud800"}}) as request:
                try:
                    result = cloud.login(accounts.load_account(self.alias), "")
                except UnicodeError as exc:
                    self.fail(f"invalid Unicode cache field must not report a failed login: {exc}")
                self.assertTrue(result["ok"])
                self.assertFalse(result["profile_saved"])
                self.assertFalse(result.get("identity_conflict", False))
                self.assertTrue(result.get("warning"))
                self.assertEqual(cloud.state_file(self.alias).read_text(), "confirmed-state")
                self.assertEqual(profiles.get(self.alias), before)
                request.assert_called_once()

    def test_inflight_public_refresh_cannot_clear_a_confirmed_uid_conflict(self):
        profiles.save_identity(self.alias, self.identity)
        def response(*args):
            profiles.mark_identity_conflict(self.alias)
            return {"profiles": [{"username": "real.profile", "profile": {**self.identity, "method": "ssr"},
                                  "posts": [{"item_id": "5001"}], "avatar_url": ""}], "failed": []}
        with patch.object(profiles, "anon_proxy", return_value="http://fixture.invalid"), \
                patch.object(cloud, "profiles", side_effect=response):
            result = profiles.fetch_now([self.alias])
        self.assertEqual([f["username"] for f in result["failed"]], [self.alias])
        self.assertTrue(profiles.identity_conflict(self.alias))
        self.assertTrue(profiles.get(self.alias)["identity_conflict"])
        with contextlib.closing(db.connect()) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM posts WHERE username = ?", (self.alias,)).fetchone()[0], 0)

    def test_disk_cache_warning_is_not_uid_conflict_and_does_not_leak_to_next_login(self):
        with patch.object(remote, "request", return_value={"ok": True, "state": "confirmed-state", "profile": self.identity}), \
                patch.object(profiles, "save_identity", side_effect=profiles.sqlite3.OperationalError("fixture disk")), \
                patch.object(signin.proxy_pool, "report_ok"):
            self.assertTrue(signin.attempt_via_server(accounts.load_account(self.alias), "", self.alias))
        flags = signin.last_warning()
        self.assertTrue(flags["warning"])
        self.assertFalse(flags["profile_saved"])
        self.assertFalse(flags.get("identity_conflict", False))
        self.assertFalse(flags.get("stop_account", False))
        with patch.object(remote, "request", return_value={"ok": True, "state": "next-state", "profile": self.identity}), \
                patch.object(signin.proxy_pool, "report_ok"):
            self.assertTrue(signin.attempt_via_server(accounts.load_account(self.alias), "", self.alias))
        self.assertEqual(signin.last_warning(), {})

    def test_account_call_rechecks_conflict_after_acquiring_the_session_lock(self):
        profiles.save_identity(self.alias, self.identity)
        cloud.state_file(self.alias).write_text("confirmed-state")
        @contextlib.contextmanager
        def waiting_lock(name):
            profiles.mark_identity_conflict(name)
            yield
        with patch.object(cloud, "_lock", side_effect=waiting_lock), patch.object(remote, "request") as request:
            with self.assertRaises(remote.RemoteError) as caught:
                cloud._call(self.alias, "/v1/photos/upload", {})
        self.assertTrue(caught.exception.stop_account)
        request.assert_not_called()

    def test_conflict_marker_write_failure_cannot_turn_a_confirmed_login_into_failure(self):
        profiles.save_identity(self.alias, self.identity)
        response = {"ok": True, "state": "confirmed-state", "profile": {
            **self.identity, "user_id": "999", "unique_id": "other.account"}}
        connect, calls = db.connect, 0
        def fail_marker():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise profiles.sqlite3.OperationalError("fixture disk")
            return connect()
        with patch.object(profiles, "require_uid"), patch.object(remote, "request", return_value=response) as request, \
                patch.object(db, "connect", side_effect=fail_marker):
            try:
                result = cloud.login(accounts.load_account(self.alias), "")
            except profiles.sqlite3.Error as exc:
                self.fail(f"confirmed login cannot be lost to quarantine cache write: {exc}")
        self.assertTrue(result["ok"])
        self.assertTrue(result["identity_conflict"])
        self.assertTrue(result["stop_account"])
        self.assertEqual(cloud.state_file(self.alias).read_text(), "confirmed-state")
        self.assertTrue(profiles.identity_conflict(self.alias))
        request.assert_called_once()

    def test_diagnostic_login_uid_conflict_is_paused_before_the_next_campaign_round(self):
        held = SimpleNamespace(url="", release=Mock())
        worker = Mock()
        worker.get_status.return_value = {"status": "stopped", "posts_done": 0, "stop_reason": "fixture refusal"}
        flags = {"warning": "Вход подтверждён, конфликт UID", "stop_account": True, "identity_conflict": True}
        with patch.object(campaign, "_stop_requested", return_value=False), patch.object(campaign, "_take_proxy", return_value=held), \
                patch.object(campaign, "_worker_set"), patch.object(campaign, "_worker_clear"), \
                patch.object(campaign, "_net_retry", return_value=({"alive": True}, False)), \
                patch.object(campaign, "_read_notices", return_value={}), patch.object(campaign, "_record_result"), \
                patch.object(campaign.batch_publish, "BatchWorker", return_value=worker), \
                patch.object(campaign, "_pause_account") as paused, patch.object(campaign, "_account_trouble", return_value=True), \
                patch.object(signin, "run", return_value=True), patch.object(signin, "last_banned", return_value=False), \
                patch.object(signin, "last_warning", return_value=flags):
            campaign._worker_run(accounts.load_account(self.alias), [], "", "", 0, 0, 1, None, itertools.count())
        paused.assert_called_once_with(self.alias)

    def test_repeated_confirmed_login_cannot_silently_clear_an_existing_uid_conflict(self):
        profiles.save_identity(self.alias, self.identity)
        profiles.mark_identity_conflict(self.alias)
        for payload in ({"profile": self.identity}, {}):
            with self.subTest(payload=payload), patch.object(remote, "request", return_value={
                    "ok": True, "state": "confirmed-state", **payload}):
                result = cloud.login(accounts.load_account(self.alias), "")
            self.assertTrue(result["ok"])
            self.assertTrue(result.get("stop_account"))
            self.assertTrue(result.get("identity_conflict"))

    def test_public_refresh_invalid_unicode_rolls_back_and_finishes_alias(self):
        profiles.save_identity(self.alias, self.identity)
        before = profiles.get(self.alias)
        response = {"profiles": [{"username": "real.profile", "profile": {
            **self.identity, "nickname": "\ud800", "method": "ssr"}, "posts": [], "avatar_url": ""}], "failed": []}
        with patch.object(profiles, "anon_proxy", return_value="http://fixture.invalid"), \
                patch.object(cloud, "profiles", return_value=response):
            try:
                result = profiles.fetch_now([self.alias])
            except UnicodeError as exc:
                self.fail(f"invalid Unicode response must fail this alias safely: {exc}")
        self.assertEqual([f["username"] for f in result["failed"]], [self.alias])
        self.assertEqual(profiles.get(self.alias), before)

    def test_account_operation_stops_before_dispatch_when_conflict_cache_is_unreadable(self):
        cloud.state_file(self.alias).write_text("confirmed-state")
        with patch.object(db, "connect", side_effect=profiles.sqlite3.OperationalError("fixture unreadable")), \
                patch.object(remote, "request") as request:
            try:
                with self.assertRaises(remote.RemoteError) as caught:
                    cloud._call(self.alias, "/v1/photos/upload", {})
            except profiles.sqlite3.Error as exc:
                self.fail(f"cache read failure must stop the account, not permit a proxy retry: {exc}")
        self.assertTrue(caught.exception.stop_account)
        self.assertFalse(caught.exception.network)
        request.assert_not_called()

    def test_uid_conflict_stop_survives_process_memory_reset(self):
        profiles.save_identity(self.alias, self.identity)
        profiles.mark_identity_conflict(self.alias)
        with patch.object(profiles, "_identity_conflicts", {}), patch.object(remote, "request") as request:
            self.assertTrue(profiles.identity_conflict(self.alias))
            self.assertTrue(accounts.list_accounts()[0]["profile"]["identity_conflict"])
            with self.assertRaises(remote.RemoteError) as caught:
                cloud._call(self.alias, "/v1/photos/upload", {})
            self.assertTrue(caught.exception.stop_account)
            request.assert_not_called()

    def test_valid_conflicting_uid_is_not_hidden_by_an_invalid_optional_cache_field(self):
        profiles.save_identity(self.alias, self.identity)
        with patch.object(remote, "request", return_value={"ok": True, "state": "confirmed-state", "profile": {
                **self.identity, "user_id": "999", "nickname": "\ud800"}}):
            result = cloud.login(accounts.load_account(self.alias), "")
        self.assertTrue(result["ok"])
        self.assertTrue(result.get("identity_conflict"))
        self.assertTrue(result.get("stop_account"))

    def test_session_check_pins_uid_before_releasing_the_account_request_lock(self):
        profiles.save_identity(self.alias, self.identity)
        cloud.state_file(self.alias).write_text("kept-state")
        @contextlib.contextmanager
        def request_lock(name):
            yield
            self.assertTrue(profiles.identity_conflict(name), "conflict must be set before the next account request can start")
        with patch.object(cloud, "_lock", side_effect=request_lock), patch.object(remote, "request", return_value={
                "data": {"alive": True, "uid": "999", "username": "other.account"}, "state": "checked-state"}):
            result = cloud.session_check(self.alias, "")
        self.assertTrue(result["stop_account"])

    def test_legacy_confirmed_login_with_unreadable_cache_is_warned_not_replayed(self):
        with patch.object(remote, "request", return_value={"ok": True, "state": "confirmed-state"}) as request, \
                patch.object(db, "connect", side_effect=profiles.sqlite3.OperationalError("fixture disk")):
            try:
                result = cloud.login(accounts.load_account(self.alias), "")
            except profiles.sqlite3.Error as exc:
                self.fail(f"legacy confirmed login must survive the cache warning: {exc}")
        self.assertTrue(result["ok"])
        self.assertTrue(result["stop_account"])
        self.assertFalse(result.get("identity_conflict", False))
        self.assertTrue(result["warning"])
        request.assert_called_once()


if __name__ == "__main__":
    unittest.main()
