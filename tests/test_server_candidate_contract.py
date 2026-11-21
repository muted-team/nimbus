"""Offline service compatibility: asynchronous jobs and preserved opaque state."""

import contextlib
import unittest
from unittest.mock import Mock, patch
from modules import client_device, remote


class ServerCandidateContractTests(unittest.TestCase):
    def setUp(self):
        stack = self.stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(
            patch.object(remote, "base", return_value="https://fixture.invalid")
        )
        stack.enter_context(patch.object(remote, "key", return_value="synthetic-key"))
        stack.enter_context(
            patch.object(remote.config, "server_wait_min", return_value=0)
        )
        stack.enter_context(patch.object(remote, "_ensure_browser_profile"))
        self.send = stack.enter_context(patch.object(remote, "_send"))
        self.sleep = stack.enter_context(patch.object(remote.time, "sleep"))

    def response(self, status, body):
        self.send.return_value = Mock(status_code=status, headers={}, json=lambda: body)

    def test_registration_uses_public_v1_and_accepts_202(self):
        with client_device.use_browser_profile("firefox155"):
            self.response(202, {"job_id": "fixture-job", "mode": 4})
            result = remote.request("POST", "/v1/register", json={"mode": 4})
        self.assertEqual(result["job_id"], "fixture-job")
        self.assertEqual(
            self.send.call_args.args[1], "https://fixture.invalid/v1/register"
        )
        self.assertFalse(self.send.call_args.kwargs["allow_redirects"])

    def test_registration_and_cancel_do_not_retry_busy_or_redirect(self):
        for path in ("/v1/register", "/v1/register/fixture/cancel"):
            with (
                self.subTest(path=path),
                client_device.use_browser_profile("chrome152"),
            ):
                self.assertTrue(remote._protected("POST", path))
                self.send.reset_mock()
                self.response(503, {"detail": "unavailable"})
                with self.assertRaises(remote.RemoteError):
                    remote.request("POST", path, json={})
                self.send.assert_called_once()
                self.sleep.assert_not_called()
                self.assertFalse(self.send.call_args.kwargs["allow_redirects"])

    def test_executor_unavailable_stops_without_waiting_or_marking_state_stale(self):
        self.sleep.side_effect = AssertionError("Do not retry a preserved state")
        self.stack.enter_context(
            patch.object(remote.config, "server_wait_min", return_value=5)
        )
        self.response(
            503,
            {
                "detail": "Состояние требует новой версии сервера",
                "code": "state_executor_unavailable",
                "state_preserved": True,
                "retriable": False,
            },
        )
        with client_device.use_browser_profile("chrome152"):
            with self.assertRaises(remote.RemoteError) as caught:
                remote.request("POST", "/v1/session/check", json={"state": "OPAQUE"})
        self.send.assert_called_once()
        self.sleep.assert_not_called()
        self.assertTrue(caught.exception.stop_account)
        self.assertFalse(caught.exception.network)
        self.assertEqual(caught.exception.code, "state_executor_unavailable")
        self.assertTrue(caught.exception.state_preserved)

    def test_profile_update_is_protected_against_transport_replay(self):
        for path in ("/v1/profile/update", "/v2/profile/update"):
            self.assertTrue(remote._protected("POST", path))

    def test_unrelated_202_is_not_treated_as_success(self):
        self.response(202, {"unexpected": True})
        with client_device.use_browser_profile("chrome152"):
            with self.assertRaises(remote.RemoteError):
                remote.request("GET", "/v1/account")


if __name__ == "__main__":
    unittest.main()
