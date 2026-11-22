"""Synthetic profile changes: Unicode names, UID readback, no write replay."""

import contextlib
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch
from modules import accounts, cloud, config, profiles, remote, paths, client_session, client_device


class ProfileClientTests(unittest.TestCase):
    def setUp(self):
        stack = self.stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        stack.enter_context(paths.use_root(self.root))
        stack.enter_context(patch.object(config, "get", side_effect=lambda key, default=None: default))
        stack.enter_context(patch.object(socket.socket, "connect", side_effect=AssertionError("network denied")))
        stack.enter_context(client_device.use_browser_profile("firefox155"))
        file = client_session.state_file("synthetic.profile")
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("KEPT")
        stack.enter_context(
            patch.object(client_session, "sticky_proxy", side_effect=lambda p, u: p)
        )
        self.request = stack.enter_context(patch.object(remote, "request"))

    def test_update_preserves_unicode_and_stops_when_state_not_saved(self):
        self.request.return_value = {
            "data": {
                "verdict": "confirmed",
                "state_saved": False,
                "confirmed_fields": ["nickname"],
            },
            "state": "KEPT",
        }
        result = cloud.profile_update(
            "synthetic.profile",
            "http://fixture.invalid",
            {"nickname": "Весна 🌷"},
            "123",
            True,
        )
        self.assertEqual(
            self.request.call_args.kwargs["json"]["changes"]["nickname"], "Весна 🌷"
        )
        self.assertEqual(
            self.request.call_args.kwargs["json"]["expected_user_id"], "123"
        )
        self.assertFalse(self.request.call_args.kwargs["retry_busy"])
        self.assertTrue(result["stop_account"])
        self.assertEqual(
            client_session.state_file("synthetic.profile").read_text(), "KEPT"
        )

    def test_unknown_transport_is_one_call_and_keeps_local_state(self):
        self.request.side_effect = remote.RemoteError(
            "synthetic timeout", stop_account=True, outcome_unknown=True
        )
        with self.assertRaises(remote.RemoteError):
            cloud.profile_update(
                "synthetic.profile",
                "http://fixture.invalid",
                {"unique_id": "new_name"},
                "123",
                True,
            )
        self.request.assert_called_once()
        self.assertEqual(
            client_session.state_file("synthetic.profile").read_text(), "KEPT"
        )

    def test_top_level_state_failure_stops_profile_readback_before_cache_merge(self):
        self.request.return_value = {"state_saved": False, "data": {
            "verdict": "observed", "before": {"user_id": "123", "unique_id": "new_name", "nickname": "other"}}}
        result = cloud.profile_info("synthetic.profile", "http://fixture.invalid")
        self.assertTrue(result.get("stop_account"))
        self.assertIs(result.get("state_saved"), False)

    def test_readback_quarantines_foreign_uid_before_releasing_the_request_lock(self):
        profiles.save_identity("synthetic.profile", {"user_id": "111", "unique_id": "synthetic.profile"})
        self.request.return_value = {"state": "SYNTHETIC_FOREIGN", "data": {"verdict": "observed", "before": {
            "user_id": "222", "unique_id": "foreign.profile", "nickname": "Foreign"}}}

        @contextlib.contextmanager
        def checked_lock(username):
            try:
                yield
            finally:
                self.assertTrue(profiles.identity_conflict(username), "Quarantine must precede the next account operation")

        with patch.object(cloud, "_lock", side_effect=checked_lock), self.assertRaises(remote.RemoteError) as caught:
            cloud.profile_info("synthetic.profile", "http://fixture.invalid")
        self.assertTrue(caught.exception.stop_account)
        self.assertEqual(client_session.state_file("synthetic.profile").read_text(), "KEPT")
        self.request.assert_called_once()


class ProfileBridgeTests(unittest.TestCase):
    def setUp(self):
        from modules import profile_edit

        self.bridge = profile_edit
        stack = self.stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        stack.enter_context(paths.use_root(self.root))
        stack.enter_context(patch.object(config, "get", side_effect=lambda key, default=None: default))
        stack.enter_context(patch.object(socket.socket, "connect", side_effect=AssertionError("network denied")))
        stack.enter_context(patch.object(remote.requests.Session, "request", side_effect=AssertionError("HTTP denied")))
        self.u = "synthetic.bridge"
        self.account = {
            "username": self.u,
            "password": "SYNTHETIC",
            "registration_proxy": "http://fixture.invalid",
        }
        stack.enter_context(
            patch(
                "modules.profile_edit.accounts.load_account", return_value=self.account
            )
        )
        stack.enter_context(
            patch.object(remote, "base", return_value="https://fixture.invalid")
        )
        stack.enter_context(patch.object(remote, "key", return_value="fixture-key"))
        self.plan = stack.enter_context(
            patch.object(
                cloud,
                "profile_plan",
                return_value={
                    "verdict": "planned",
                    "network_performed": False,
                    "requested": {"unique_id": "new_name"},
                },
            )
        )
        self.send = stack.enter_context(patch.object(cloud, "profile_update"))
        self.read = stack.enter_context(
            patch.object(
                cloud,
                "profile_info",
                return_value={
                    "verdict": "observed",
                    "before": {
                        "user_id": "123",
                        "nickname": "Весна 🌷",
                        "unique_id": "new_name",
                    },
                    "policies": {},
                },
            )
        )

    def test_unknown_saved_before_dispatch_and_requires_readback(self):
        def unknown(*args):
            self.assertEqual(self.bridge._read(self.u)["result"]["verdict"], "unknown")
            raise remote.RemoteError("synthetic timeout", outcome_unknown=True)

        self.send.side_effect = unknown
        result = self.bridge.update(self.u, {"unique_id": "NEW_NAME"}, "123", True)
        self.assertEqual(result["verdict"], "unknown")
        self.assertEqual(self.send.call_args.args[2]["unique_id"], "new_name")
        with self.assertRaises(ValueError):
            self.bridge.update(self.u, {"unique_id": "NEW_NAME"}, "123", True)
        self.send.assert_called_once()
        info = self.bridge.info(self.u)
        self.assertEqual(info["last_result"]["verdict"], "unknown")
        self.assertTrue(self.bridge._read(self.u)["reconciled"])

    def test_partial_unknown_username_is_not_replayed(self):
        self.send.return_value = {
            "verdict": "partial",
            "confirmed_fields": ["nickname"],
            "steps": [{"step": "username_update", "verdict": "unknown"}],
        }
        self.bridge.update(self.u, {"unique_id": "new_name"}, "123", True)
        with self.assertRaises(ValueError):
            self.bridge.update(self.u, {"unique_id": "other_name"}, "123", True)
        self.send.assert_called_once()

    def test_contradictory_server_confirmation_requires_readback_before_next_write(
        self,
    ):
        self.send.return_value = {
            "verdict": "confirmed",
            "before": {"user_id": "123"},
            "after": {"user_id": "999", "unique_id": "new_name"},
            "confirmed_fields": ["unique_id"],
            "platform_verified": True,
        }
        result = self.bridge.update(self.u, {"unique_id": "new_name"}, "123", True)
        self.assertEqual(
            result["verdict"], "confirmed"
        )  # Preserve raw server status for diagnostics.
        with self.assertRaises(ValueError):
            self.bridge.update(self.u, {"unique_id": "new_name"}, "123", True)
        self.send.assert_called_once()

    def test_name_formats_are_delegated_to_server_and_emoji_are_preserved(self):
        self.plan.return_value = {
            "verdict": "planned",
            "network_performed": False,
            "requested": {"nickname": "Весна 🌷"},
        }
        self.send.return_value = {
            "verdict": "blocked",
            "confirmed_fields": [],
            "message": "SYNTHETIC constraint",
        }
        self.bridge.update(self.u, {"nickname": "Весна 🌷"}, "123", True)
        self.assertEqual(self.send.call_args.args[2]["nickname"], "Весна 🌷")
        self.assertEqual(self.bridge._read(self.u)["result"]["verdict"], "blocked")

    def test_existing_email_alias_info_populates_sqlite_without_renaming_login(self):
        alias = "profile@example.invalid"
        accounts.add_accounts_bulk(alias + ":synthetic-password")
        self.account["username"] = alias
        registry = paths.here(accounts.ACCOUNTS_FILE).read_bytes()
        try:
            info = self.bridge.info(alias)
        except ValueError as exc:
            self.fail(f"existing email login must be accepted: {exc}")
        self.read.assert_called_once_with(alias, "http://fixture.invalid")
        self.assertEqual(profiles.get(alias)["user_id"], info["before"]["user_id"])
        self.assertEqual(profiles.get(alias)["unique_id"], "new_name")
        self.assertEqual(paths.here(accounts.ACCOUNTS_FILE).read_bytes(), registry)
        self.assertIsNone(profiles.get("new_name"))

    def test_unconfirmed_info_does_not_populate_or_replace_cached_identity(self):
        identity = {"user_id": "123", "unique_id": "kept_name", "nickname": "kept"}
        profiles.save_identity(self.u, identity)
        before = profiles.get(self.u)
        for flags in ({"state_saved": False}, {"stop_account": True}, {"verdict": "unknown"},
                      {"before": {"user_id": "999", "unique_id": "new_name", "nickname": "other"}},
                      {"before": {"user_id": "123", "unique_id": "bad/name", "nickname": "other"}}):
            self.read.return_value = {"verdict": "observed", "before": {
                "user_id": "123", "unique_id": "new_name", "nickname": "other"}, **flags}
            with self.subTest(flags=flags):
                with self.assertRaises(ValueError):
                    self.bridge.info(self.u)
                self.assertEqual(profiles.get(self.u), before)

    def test_info_cache_failure_keeps_confirmed_readback_usable(self):
        with patch.object(profiles, "save_identity", side_effect=profiles.sqlite3.OperationalError("fixture disk")):
            try:
                result = self.bridge.info(self.u)
            except profiles.sqlite3.Error as exc:
                self.fail(f"cache failure must not discard a confirmed readback: {exc}")
        self.assertEqual(result["verdict"], "observed")
        self.assertFalse(result["profile_saved"])
        self.read.assert_called_once()

    def test_profile_alias_validation_rejects_unknown_email_and_paths_before_requests(self):
        for name in ("unknown@example.invalid", "../known@example.invalid", "known\\a@example.invalid",
                     "known\x00@example.invalid", "../synthetic.bridge", "synthetic.bridge\n"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.bridge.info(name)
        self.read.assert_not_called()

    def test_confirmed_same_uid_update_merges_identity_into_existing_sqlite_profile(self):
        alias = "profile@example.invalid"
        accounts.add_accounts_bulk(alias + ":synthetic-password")
        self.account["username"] = alias
        profiles.save_row(alias, {"user_id": "123", "unique_id": "old_name", "nickname": "kept",
                                  "followers": 42, "method": "ssr"})
        profiles.save_posts(alias, [{"id": "5001", "desc": "kept post"}])
        before = profiles.get(alias)
        response = {"verdict": "confirmed", "before": {"user_id": "123"},
                    "after": {"user_id": "123", "unique_id": "new_name", "nickname": "Весна 🌷"},
                    "confirmed_fields": ["unique_id"], "platform_verified": True}
        self.send.return_value = response
        result = self.bridge.update(alias, {"unique_id": "new_name"}, "123", True)
        self.assertEqual(result, response)
        self.assertEqual(profiles.get(alias), {**before, "unique_id": "new_name", "nickname": "Весна 🌷"})
        self.assertEqual(profiles.posts_of(alias)[0]["item_id"], "5001")
        self.send.assert_called_once()
        self.assertEqual(self.send.call_args.args[0], alias)
        self.assertIsNone(profiles.get("new_name"))

    def test_uncertain_rejected_or_wrong_uid_update_never_changes_cached_identity(self):
        identity = {"user_id": "123", "unique_id": "kept_name", "nickname": "kept"}
        profiles.save_identity(self.u, identity)
        before = profiles.get(self.u)
        confirmed = {"verdict": "confirmed", "before": {"user_id": "123"},
                     "after": {"user_id": "123", "unique_id": "new_name", "nickname": "other"},
                     "confirmed_fields": ["unique_id"], "platform_verified": True}
        for flags in ({"verdict": "unknown"}, {"verdict": "rejected"}, {"state_saved": False},
                      {"stop_account": True}, {"after": {"user_id": "999", "unique_id": "new_name", "nickname": "other"}},
                      {"platform_verified": False}, {"confirmed_fields": []},
                      {"steps": [{"verdict": "unknown"}]}):
            self.send.return_value = {**confirmed, **flags}
            with self.subTest(flags=flags):
                self.bridge._save(self.u, {"reconciled": True})
                self.bridge.update(self.u, {"unique_id": "new_name"}, "123", True)
                self.assertEqual(profiles.get(self.u), before)

    def test_confirmed_update_cache_failure_does_not_become_an_unknown_mutation(self):
        self.send.return_value = {"verdict": "confirmed", "before": {"user_id": "123"},
            "after": {"user_id": "123", "unique_id": "new_name", "nickname": "other"},
            "confirmed_fields": ["unique_id"], "platform_verified": True}
        with patch.object(profiles, "save_identity", side_effect=profiles.sqlite3.OperationalError("fixture disk")):
            result = self.bridge.update(self.u, {"unique_id": "new_name"}, "123", True)
        self.assertEqual(result["verdict"], "confirmed")
        self.assertFalse(result["profile_saved"])
        self.assertFalse(self.bridge._requires_readback(self.bridge._read(self.u)))
        self.send.assert_called_once()


if __name__ == "__main__":
    unittest.main()
