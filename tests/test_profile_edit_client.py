"""Synthetic profile changes: Unicode names, UID readback, no write replay."""

import contextlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from modules import cloud, remote, paths, client_session, client_device


class ProfileClientTests(unittest.TestCase):
    def setUp(self):
        stack = self.stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        stack.enter_context(paths.use_root(self.root))
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


class ProfileBridgeTests(unittest.TestCase):
    def setUp(self):
        from modules import profile_edit

        self.bridge = profile_edit
        stack = self.stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        stack.enter_context(paths.use_root(self.root))
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


if __name__ == "__main__":
    unittest.main()
