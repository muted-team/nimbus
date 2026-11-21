"""Synthetic registration jobs: no TikTok, credentials or external requests."""

import contextlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from modules import (
    registration as reg,
    paths,
    accounts,
    client_session,
    client_device,
    remote,
)

JOB = "a" * 32


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        stack = self.stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        stack.enter_context(paths.use_root(self.root))
        stack.enter_context(client_device.use_browser_profile("firefox155"))
        stack.enter_context(
            patch.object(remote, "base", return_value="https://fixture.invalid")
        )
        stack.enter_context(patch.object(remote, "key", return_value="fixture"))
        self.request = stack.enter_context(patch.object(remote, "request"))

        self.cap = {
            "modes": [
                {"mode": m, "supported": True, "available": True} for m in (2, 3, 4)
            ]
        }
        self.body = {
            "mode": 4,
            "proxy": "http://fixture.invalid",
            "anymessage_token": "SYNTHETIC",
            "country": "US",
        }

    def start(self):
        self.request.side_effect = [self.cap, {"job_id": JOB}]
        return reg.start(self.body)

    def test_real_modes_only_and_no_silent_fallback(self):
        self.request.return_value = self.cap
        self.assertEqual([m["mode"] for m in reg.capabilities()["modes"]], [2, 3, 4])
        for mode in (1, 2, True):
            with self.assertRaises(ValueError):
                reg.start({**self.body, "mode": mode})
        self.request.assert_called_once()

    def test_start_once_and_receipt_survives_unknown(self):
        self.request.side_effect = [self.cap, remote.RemoteError("unknown")]
        with self.assertRaises(remote.RemoteError):
            reg.start(self.body)
        self.assertEqual(reg.status()["status"], "dispatch_unknown")
        with self.assertRaises(ValueError):
            reg.start(self.body)
        self.assertNotIn(
            "anymessage_token", (self.root / "registration/current.json").read_text(encoding="utf-8")
        )

    def test_completed_account_states_saved_separately_without_secrets_to_ui(self):
        self.start()
        result = {
            "ok": True,
            "username": "synthetic.new",
            "uid": "123",
            "password": "SYNTHETIC_PASSWORD",
            "email": "fixture@example.invalid",
            "state": "OPAQUE_HTTP_STATE",
            "browser_state": "OPAQUE_BROWSER_STATE",
        }
        self.request.side_effect = None
        self.request.return_value = {"status": "complete", "result": result}
        status = reg.status()
        self.assertTrue(status["account_saved"])
        self.assertNotIn("PASSWORD", json.dumps(status))
        self.assertNotIn("OPAQUE", json.dumps(status))
        state = client_session.state_file("synthetic.new")
        self.assertEqual(state.read_text(), "OPAQUE_HTTP_STATE")
        self.assertEqual(
            state.with_suffix(".browser.state").read_text(), "OPAQUE_BROWSER_STATE"
        )
        if os.name != "nt":
            self.assertEqual(state.stat().st_mode & 0o777, 0o600)
        self.assertEqual(
            accounts._read_raw()["accounts"][0]["password"], "SYNTHETIC_PASSWORD"
        )
        self.request.reset_mock()
        self.assertTrue(reg.status()["account_saved"])
        self.request.assert_not_called()

    def test_complete_without_creation_evidence_blocks_duplicate_registration(self):
        self.start()
        self.request.side_effect = None
        self.request.return_value = {"status": "complete"}
        self.assertEqual(reg.status()["status"], "interrupted_or_unknown")
        self.request.reset_mock()
        with self.assertRaises(ValueError):
            reg.start(self.body)
        self.request.assert_not_called()

    def test_existing_account_is_never_overwritten(self):
        self.start()
        accounts._write_json(
            self.root / "accounts.json",
            {"accounts": [{"username": "synthetic.new", "password": "KEEP"}]},
        )
        self.request.side_effect = None
        self.request.return_value = {
            "status": "complete",
            "result": {
                "ok": True,
                "username": "synthetic.new",
                "uid": "123",
                "password": "NEW",
                "email": "fixture@example.invalid",
                "state": "STATE",
                "browser_state": "BROWSER",
            },
        }
        status = reg.status()
        self.assertEqual(status["status"], "interrupted_or_unknown")
        self.assertEqual(accounts._read_raw()["accounts"][0]["password"], "KEEP")
        self.assertTrue((self.root / "registration" / f"{JOB}.result.json").exists())

    def test_created_account_retains_exact_signup_proxy_for_later_steps(self):
        self.start()
        self.request.side_effect = None
        self.request.return_value = {
            "status": "complete",
            "result": {
                "ok": True,
                "username": "synthetic.route",
                "uid": "123",
                "password": "NEW",
                "email": "fixture@example.invalid",
                "state": "STATE",
                "browser_state": "BROWSER",
            },
        }
        self.assertTrue(reg.status()["account_saved"])
        from modules import cloud

        with patch.object(
            client_session,
            "sticky_proxy",
            side_effect=AssertionError("Do not rotate signup proxy"),
        ):
            self.assertEqual(
                cloud._account_proxy("synthetic.route", "http://different.invalid"),
                self.body["proxy"],
            )
        accounts.add_account({"username": "synthetic.route", "password": "NEW2"})
        self.assertEqual(
            cloud._account_proxy("synthetic.route", "http://different.invalid"),
            self.body["proxy"],
        )

    def test_partial_checkpoint_keeps_polling_until_terminal_billing_result(self):
        self.start()
        self.request.side_effect = None
        result = {
            "ok": True,
            "username": "synthetic.checkpoint",
            "uid": "123",
            "password": "NEW",
            "email": "fixture@example.invalid",
            "state": "STATE",
            "browser_state": "BROWSER",
        }
        self.request.return_value = {"status": "running", "result": result}
        self.assertTrue(reg.status()["account_saved"])
        self.request.return_value = {
            "status": "complete",
            "result": {**result, "billing_status": "unknown"},
        }
        final = reg.status()
        self.assertEqual(final["status"], "complete")
        self.assertEqual(final["billing_status"], "unknown")

    def test_fixture_success_never_imports_as_created_account(self):
        self.start()
        self.request.side_effect = None
        self.request.return_value = {
            "status": "complete",
            "result": {
                "ok": True,
                "account_created": False,
                "username": "synthetic.fixture",
                "uid": "123",
                "password": "NEW",
                "email": "fixture@example.invalid",
                "state": "STATE",
                "browser_state": "BROWSER",
            },
        }
        self.assertEqual(reg.status()["status"], "interrupted_or_unknown")
        self.assertEqual(accounts._read_raw()["accounts"], [])

    def test_registry_failure_rolls_back_both_state_kinds_and_keeps_recovery(self):
        self.start()
        self.request.side_effect = None
        self.request.return_value = {
            "status": "complete",
            "result": {
                "ok": True,
                "username": "synthetic.disk",
                "uid": "123",
                "password": "SYNTHETIC",
                "email": "fixture@example.invalid",
                "state": "STATE",
                "browser_state": "BROWSER",
            },
        }
        original_write = accounts._write_json

        def interrupted(path, data):
            original_write(path, data)
            raise OSError("synthetic after registry replacement")

        with patch.object(accounts, "_write_json", side_effect=interrupted):
            self.assertEqual(reg.status()["status"], "interrupted_or_unknown")
        self.assertEqual(accounts._read_raw()["accounts"], [])
        self.assertFalse(client_session.state_file("synthetic.disk").exists())
        self.assertFalse(
            client_session.state_file("synthetic.disk")
            .with_suffix(".browser.state")
            .exists()
        )
        self.assertTrue((self.root / "registration" / f"{JOB}.result.json").exists())

    def test_confirmed_admission_rejection_does_not_leave_an_unknown_dispatch(self):
        self.request.side_effect = [
            self.cap,
            remote.RemoteError("synthetic invalid input", 422),
        ]
        with self.assertRaises(remote.RemoteError):
            reg.start(self.body)
        self.assertEqual(reg.status()["status"], "failed")
        self.assertNotIn("job_id", reg.status())

    def test_browser_state_is_cleared_and_registered_owner_is_not_relabelled(self):
        self.start()
        self.request.side_effect = None
        self.request.return_value = {
            "status": "complete",
            "result": {
                "ok": True,
                "username": "synthetic.bound",
                "uid": "123",
                "password": "SYNTHETIC",
                "email": "fixture@example.invalid",
                "state": "HTTP",
                "browser_state": "BROWSER",
            },
        }
        self.assertTrue(reg.status()["account_saved"])
        state = client_session.state_file("synthetic.bound")
        with self.assertRaises(ValueError):
            accounts.update_account("synthetic.bound", {"username": "different_name"})
        self.assertEqual(state.read_text(), "HTTP")
        with (
            patch("modules.avatars.versions", return_value={}),
            patch("modules.profiles.summaries", return_value={}),
        ):
            accounts.update_account("synthetic.bound", {"password": "CHANGED"})
        self.assertEqual(
            accounts._read_raw()["accounts"][0]["registration_proxy"],
            self.body["proxy"],
        )
        client_session.clear_session("synthetic.bound", new_device=True)
        self.assertFalse(state.exists())
        self.assertFalse(state.with_suffix(".browser.state").exists())

    def test_final_job_response_does_not_revive_a_deleted_checkpoint_account(self):
        self.start()
        self.request.side_effect = None
        result = {
            "ok": True,
            "username": "synthetic.deleted",
            "uid": "123",
            "password": "SYNTHETIC",
            "email": "fixture@example.invalid",
            "state": "HTTP",
            "browser_state": "BROWSER",
        }
        self.request.return_value = {"status": "running", "result": result}
        self.assertTrue(reg.status()["account_saved"])
        accounts._write_json(self.root / "accounts.json", {"accounts": []})
        client_session.clear_session("synthetic.deleted", new_device=True)
        self.request.return_value = {"status": "complete", "result": result}
        self.assertEqual(reg.status()["status"], "complete")
        self.assertEqual(accounts._read_raw()["accounts"], [])
        self.assertFalse(client_session.state_file("synthetic.deleted").exists())

    def test_concrete_username_is_not_forwarded_or_submitted(self):
        with self.assertRaises(ValueError):
            reg.start({**self.body, "unique_id": "chosen.name"})
        self.request.assert_not_called()

    def test_optional_username_failure_preserves_created_account_and_states(self):
        self.start()
        self.request.side_effect = None
        self.request.return_value = {
            "status": "complete",
            "result": {
                "ok": True,
                "username": "assigned.name",
                "uid": "123",
                "password": "SYNTHETIC",
                "email": "fixture@example.invalid",
                "state": "HTTP",
                "browser_state": "BROWSER",
                "username_selection": {
                    "requested": "desired.name",
                    "status": "unavailable",
                    "reason": "unavailable",
                },
            },
        }
        status = reg.status()
        self.assertTrue(status["account_saved"])
        self.assertEqual(status["username"], "assigned.name")
        self.assertEqual(status["username_selection"]["status"], "unavailable")
        self.assertEqual(client_session.state_file("assigned.name").read_text(), "HTTP")

    def test_pool_lease_is_retained_until_terminal_and_history_is_public_only(self):
        from unittest.mock import Mock

        cap = {**self.cap, "geo_policy": "proxy_auto_v1"}
        held = Mock(url="socks5://fixture-country-AU:password@proxy.noshadow.pro:9696")
        self.request.side_effect = [cap, {"job_id": JOB}]
        with patch.object(reg.proxy_pool, "lease", return_value=held) as lease:
            reg.start(
                {"mode": 4, "anymessage_token": "SYNTHETIC", "domains": ["gmail.com"]}
            )
            lease.assert_called_once_with(task="registration")
            sent = self.request.call_args.kwargs["json"]
            self.assertTrue(sent["proxy"].startswith("http://"))
            self.assertNotIn("country", sent)
            held.release.assert_not_called()
            with self.assertRaises(ValueError):
                reg.start({"mode": 4, "anymessage_token": "SYNTHETIC"})
            lease.assert_called_once()
        self.request.side_effect = None
        self.request.return_value = {
            "status": "complete",
            "result": {
                "ok": True,
                "username": "pool.user",
                "uid": "123",
                "password": "SECRET",
                "email": "fixture@gmail.com",
                "state": "HTTP",
                "browser_state": "BROWSER",
            },
        }
        self.assertTrue(reg.status()["account_saved"])
        held.release.assert_called_once()
        rows = reg.history()["results"]
        self.assertEqual(rows[0]["username"], "pool.user")
        self.assertEqual(rows[0]["email_domain"], "gmail.com")
        self.assertNotIn("password", json.dumps(rows))
        self.assertNotIn("proxy.noshadow", json.dumps(rows))

    def test_auto_geography_does_not_guess_or_allocate_before_live_marker(self):
        self.request.return_value = self.cap
        with patch.object(reg.proxy_pool, "lease") as lease:
            with self.assertRaises(ValueError):
                reg.start({"mode": 4, "anymessage_token": "SYNTHETIC"})
        lease.assert_not_called()

    def test_domains_are_normalized_and_randomized_without_sender_override(self):
        self.request.side_effect = [self.cap, {"job_id": JOB}]
        with patch.object(
            reg.random.SystemRandom,
            "shuffle",
            side_effect=lambda values: values.reverse(),
        ):
            reg.start(
                {
                    **self.body,
                    "domains": ["Gmail.com", "outlook.com", "gmail.com"],
                    "sender": "not-forwarded",
                }
            )
        sent = self.request.call_args.kwargs["json"]
        self.assertEqual(sent["domains"], ["outlook.com", "gmail.com"])
        self.assertNotIn("sender", sent)
        self.assertNotIn("unique_id", sent)

    def test_changed_server_or_key_stops_before_metadata_or_admission(self):
        with self.assertRaises(ValueError):
            reg.start({**self.body, "expected_scope": "changed"})
        self.request.assert_not_called()

    def test_old_server_capabilities_gracefully_unavailable(self):
        self.request.side_effect = remote.RemoteError("missing", 404)
        self.assertEqual(reg.capabilities(), {"modes": [], "unavailable": True})


if __name__ == "__main__":
    unittest.main()


class BrowserOnlyRegistrationTests(unittest.TestCase):
    setUp = RegistrationTests.setUp
    start = RegistrationTests.start

    def result(self):
        return {
            "ok": True,
            "account_created": True,
            "state_saved": True,
            "same_uid_verified": True,
            "uid": "123",
            "username": "synthetic.browser",
            "password": "Synthetic9!",
            "email": "fixture@example.invalid",
            "state_kind": "browser_only_v1",
            "state": None,
            "http_state": None,
            "browser_state": "OPAQUE_NATIVE_ONLY",
        }

    def begin_browser(self):
        self.cap["browser_only_state_v1"] = True
        self.start()
        self.request.side_effect = None
        self.request.return_value = {"status": "complete", "result": self.result()}

    def test_browser_only_marker_saves_atomic_native_namespaces_without_http_state(
        self,
    ):
        self.begin_browser()
        status = reg.status()
        self.assertTrue(status["account_saved"])
        entry = accounts._read_raw()["accounts"][0]
        self.assertTrue(entry["http_disabled"])
        self.assertEqual(entry["state_kind"], "browser_only_v1")
        from modules import execution

        http = client_session.state_file("synthetic.browser")
        self.assertFalse(http.exists())
        self.assertEqual(
            http.with_suffix(".browser.state").read_text(), "OPAQUE_NATIVE_ONLY"
        )
        self.assertEqual(
            execution.store().read("synthetic.browser", 4), "OPAQUE_NATIVE_ONLY"
        )

    def test_marker_without_negotiated_capability_stays_unknown_and_keeps_recovery(
        self,
    ):
        self.start()
        self.request.side_effect = None
        self.request.return_value = {"status": "complete", "result": self.result()}
        value = reg.status()
        self.assertEqual(value["status"], "interrupted_or_unknown")
        self.assertFalse(value.get("account_saved", False))
        self.assertTrue((self.root / "registration" / (JOB + ".result.json")).exists())
        self.assertFalse((self.root / "accounts.json").exists())

    def test_atomic_native_save_rolls_back_both_capsules_if_registry_fails(self):
        self.begin_browser()
        with patch.object(
            accounts, "_write_json", side_effect=OSError("synthetic disk error")
        ):
            value = reg.status()
        self.assertEqual(value["status"], "interrupted_or_unknown")
        from modules import execution

        http = client_session.state_file("synthetic.browser")
        self.assertFalse(http.exists())
        self.assertFalse(http.with_suffix(".browser.state").exists())
        self.assertIsNone(execution.store().read("synthetic.browser", 4))
        self.assertFalse((self.root / "accounts.json").exists())

    def test_saved_browser_only_account_never_triggers_http_import_or_login(self):
        self.begin_browser()
        self.assertTrue(reg.status()["account_saved"])
        from modules import cloud, execution

        self.request.reset_mock()
        self.request.side_effect = AssertionError("HTTP dispatch forbidden")
        entry = accounts._read_raw()["accounts"][0]
        with patch.object(execution, "selected", return_value=0):
            with self.assertRaises(remote.RemoteError):
                cloud.login(entry, "")
            with self.assertRaises(remote.RemoteError):
                cloud.profile_info(entry["username"], "")
            check = cloud.session_check(entry["username"], "")
            self.assertTrue(check["stop_account"])
        self.request.assert_not_called()

    def test_browser_only_malformed_proofs_never_save_account(self):
        self.cap["browser_only_state_v1"] = True
        self.start()
        row = reg._load()
        for patch_result in (
            {"state_kind": "browser_only_v2"},
            {"state": "FORBIDDEN_HTTP"},
            {"http_state": "FORBIDDEN_HTTP"},
            {"same_uid_verified": False},
            {"state_saved": False},
            {"account_created": False},
        ):
            with self.subTest(patch_result=patch_result), self.assertRaises(ValueError):
                reg._accept(row, {**self.result(), **patch_result})
        self.assertFalse((self.root / "accounts.json").exists())

    def test_browser_only_flags_survive_account_edit_and_reimport(self):
        self.begin_browser()
        self.assertTrue(reg.status()["account_saved"])
        name = "synthetic.browser"
        accounts.update_account(name, {"password": "Changed9!"})
        self.assertTrue(accounts._read_raw()["accounts"][0]["http_disabled"])
        accounts.add_account({"username": name, "password": "Again9!"})
        self.assertEqual(
            accounts._read_raw()["accounts"][0]["state_kind"], "browser_only_v1"
        )
        accounts.add_accounts_bulk(name + ":Bulk9!")
        self.assertTrue(accounts._read_raw()["accounts"][0]["http_disabled"])

    def test_explicit_browser_login_remains_separate_from_http(self):
        self.begin_browser()
        self.assertTrue(reg.status()["account_saved"])
        from modules import cloud, execution

        entry = accounts._read_raw()["accounts"][0]
        self.request.reset_mock()
        self.request.side_effect = AssertionError("HTTP forbidden")
        with (
            patch.object(execution, "selected", return_value=4),
            patch.object(execution, "run_account", return_value={"ok": True}) as native,
        ):
            self.assertTrue(cloud.login(entry, "")["ok"])
            native.assert_called_once()
        self.request.assert_not_called()
