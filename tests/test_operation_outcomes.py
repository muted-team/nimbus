"""Synthetic server-result regressions without accounts or external requests."""
import contextlib
import itertools
from pathlib import Path
import socket
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules import campaign, client_device, cloud, config, paths, purge, remote, signin


class OperationOutcomesTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(paths.use_root(self.root))
        self.stack.enter_context(client_device.use_browser_profile("chrome152"))
        self.stack.enter_context(patch.object(config, "get", side_effect=lambda key, default=None: default))
        for name in ("connect", "connect_ex"):
            self.stack.enter_context(patch.object(socket.socket, name, side_effect=AssertionError("network denied")))
        self.stack.enter_context(patch.object(remote.requests.Session, "request",
                                             side_effect=AssertionError("HTTP denied")))

    def test_unknown_or_malformed_check_stops_without_network_retry(self):
        replies = ({"data": {"alive": False, "verdict": "unknown", "network": True}},
                   {"data": {"alive": True}, "state_saved": False}, {"data": []}, {})
        for reply in replies:
            with self.subTest(reply=reply), patch.object(cloud, "_call", return_value=reply):
                result = cloud.session_check("synthetic.user", "http://synthetic.invalid")
                self.assertFalse(result["alive"])
                self.assertFalse(result.get("network"))
                self.assertTrue(result["stop_account"])
                self.assertEqual(result["verdict"], "unknown")

    def test_legacy_check_keeps_its_response(self):
        for data in ({"alive": True, "uid": "123", "username": "synthetic.user"},
                     {"alive": False, "stale": True, "error": "expired cookie"},
                     {"alive": False, "network": True, "error": "transport failed"},
                     {"alive": False, "http_status": 401}):
            with self.subTest(data=data), patch.object(cloud, "_call", return_value={"data": data}):
                self.assertEqual(cloud.session_check("synthetic.user", "http://synthetic.invalid"), data)

    def test_legacy_errors_and_unexpected_http_status_are_terminal(self):
        cases = ({"alive": False, "error": "synthetic invalid JSON"},
                 {"alive": False, "http_status": 200, "message": "error"},
                 {"alive": False, "http_status": 403},
                 {"alive": False, "http_status": 429},
                 {"alive": False, "http_status": 500},
                 {"alive": True, "http_status": 302, "uid": "123"},
                 {"alive": True, "http_status": 401, "uid": "123"},
                 {"alive": True}, {"alive": True, "uid": False})
        for data in cases:
            with self.subTest(data=data), patch.object(cloud, "_call", return_value={"data": data}):
                result = cloud.session_check("synthetic.user", "http://synthetic.invalid")
                self.assertFalse(result["alive"])
                self.assertTrue(result["stop_account"])
                self.assertFalse(result.get("network"))

    def test_missing_or_empty_local_session_allows_first_login(self):
        state = cloud.state_file('synthetic.user')
        for stored in (None, '   '):
            with self.subTest(stored=stored):
                if stored is not None:
                    state.write_text(stored)
                with patch.object(remote, 'request') as request:
                    result = cloud.session_check('synthetic.user', '')
                self.assertFalse(result['alive'])
                self.assertTrue(result['stale'])
                self.assertFalse(result.get('stop_account'))
                request.assert_not_called()

    def test_unconfirmed_import_is_not_treated_as_a_fresh_account(self):
        jar = cloud.session_manager.session_file('synthetic.user')
        jar.write_text('{"synthetic":"old-cookies"}')
        with patch.object(remote, 'request', return_value={}) as request:
            result = cloud.session_check('synthetic.user', '')
        self.assertTrue(result['stop_account'])
        self.assertFalse(result.get('stale'))
        self.assertEqual(jar.read_text(), '{"synthetic":"old-cookies"}')
        request.assert_called_once()

    def test_failed_state_save_remains_terminal(self):
        error = remote.RemoteError("synthetic state changed", stop_account=True)
        with patch.object(cloud, "_call", side_effect=error):
            self.assertTrue(cloud.session_check("synthetic.user", "http://synthetic.invalid")["stop_account"])

    def test_local_state_io_failure_stops_before_login(self):
        with patch.object(cloud, '_call', side_effect=OSError('synthetic state read failure')):
            result = cloud.session_check('synthetic.user', '')
        self.assertFalse(result['alive'])
        self.assertTrue(result['stop_account'])
        self.assertFalse(result.get('network'))

    def test_disk_error_while_saving_check_is_terminal(self):
        with patch.object(cloud, "_state", return_value="synthetic-old"), \
                patch.object(cloud, "_save", side_effect=OSError("fixture disk")), \
                patch.object(remote, "request", return_value={"data": {"alive": True}, "state": "synthetic-new"}):
            result = cloud.session_check("synthetic.user", "")
            self.assertFalse(result["alive"])
            self.assertTrue(result["stop_account"])

    def test_campaign_stops_before_login_and_publication_after_unknown_check(self):
        held = SimpleNamespace(url="http://synthetic.invalid", release=Mock())
        result = {"alive": False, "verdict": "unknown", "network": True}
        with contextlib.ExitStack() as stack:
            for name, value in (("_stop_requested", False), ("_take_proxy", held)):
                stack.enter_context(patch.object(campaign, name, return_value=value))
            for name in ("_worker_set", "_worker_clear", "_record_result"):
                stack.enter_context(patch.object(campaign, name))
            paused = stack.enter_context(patch.object(campaign, "_pause_account"))
            failed = stack.enter_context(patch.object(campaign, "_fail_account"))
            switched = stack.enter_context(patch.object(campaign, "_switch_proxy"))
            stack.enter_context(patch.object(campaign.proxies_mod, "entry_for", return_value=None))
            stack.enter_context(patch.object(campaign.eventlog, "say"))
            checked = stack.enter_context(patch.object(cloud, "session_check", return_value=result))
            login = stack.enter_context(patch.object(signin, "run", return_value=False))
            notices = stack.enter_context(patch.object(campaign, "_read_notices"))
            campaign._worker_run({"username": "synthetic.user"}, [], "", "", 0, 0,
                                 1, None, itertools.count())
        checked.assert_called_once()
        switched.assert_not_called()
        login.assert_not_called()
        notices.assert_not_called()
        paused.assert_called_once_with("synthetic.user")
        failed.assert_called_once()
        held.release.assert_called_once()

    def test_delete_and_logout_dispatch_once_without_redirects(self):
        for path in ("/v1/posts/delete", "/v1/logout", "/v2/posts/delete", "/v2/logout"):
            for response in (SimpleNamespace(status_code=503, headers={}), TimeoutError("fixture")):
                with self.subTest(path=path, response=response), \
                        patch.object(config, "server_wait_min", return_value=1), \
                        patch.object(remote, "_send", side_effect=[response]) as send, \
                        patch.object(remote.time, "sleep") as sleep:
                    with self.assertRaises(remote.RemoteError) as caught:
                        remote.request("POST", path, api_key="synthetic-key")
                    self.assertTrue(caught.exception.stop_account)
                    self.assertFalse(caught.exception.network)
                    send.assert_called_once()
                    self.assertFalse(send.call_args.kwargs["allow_redirects"])
                    sleep.assert_not_called()

    def test_delete_and_logout_do_not_retry_stale_state(self):
        for path in ("/v1/posts/delete", "/v1/logout"):
            with self.subTest(path=path), patch.object(cloud, "_state", return_value="synthetic-state"), \
                    patch.object(cloud, "_stale_retry") as stale, \
                    patch.object(remote, "request", side_effect=remote.RemoteError("stale", 409)) as send:
                with self.assertRaises(remote.RemoteError) as caught:
                    cloud._call("synthetic.user", path, {})
                self.assertTrue(caught.exception.stop_account)
                stale.assert_not_called()
                send.assert_called_once()

    def test_purge_does_not_report_success_after_terminal_result(self):
        for flags in ({"stop_account": True}, {"state_saved": False}, {"verdict": "unknown"}):
            result = {"deleted": 0, "failed": [], "total": 0, **flags}
            with self.subTest(flags=flags), patch.object(cloud, "delete_posts", return_value=result), \
                    patch.object(purge, "note") as note:
                with self.assertRaises(remote.RemoteError) as caught:
                    purge.run_one("synthetic.user", "http://synthetic.invalid", 1)
                self.assertTrue(caught.exception.stop_account)
                self.assertIn("error", note.call_args.args[1])

    def test_legacy_delete_counts_still_work(self):
        result = {"deleted": 1, "failed": [], "total": 1}
        with patch.object(cloud, "delete_posts", return_value=result), patch.object(purge, "note"):
            self.assertEqual(purge.run_one("synthetic.user", "http://synthetic.invalid", 1), result)

    def test_cookie_only_login_stops_on_unknown_session_check(self):
        with patch.object(cloud, "session_check", return_value={"alive": False, "stop_account": True}), \
                patch.object(cloud, "login") as login, \
                patch.object(cloud.session_manager, "sticky_proxy", return_value="http://synthetic.invalid"), \
                patch.object(signin.proxy_pool, "report_ok") as report:
            self.assertFalse(signin.attempt_via_server({"username": "synthetic.user"},
                                                      "http://synthetic.invalid", "synthetic.user"))
            login.assert_not_called()
            report.assert_not_called()

    def test_unconfirmed_logout_keeps_auth_state(self):
        state = cloud.state_file("synthetic.user")
        state.write_text("synthetic-state")
        for result in ({"ok": False, "confirmed": "false"}, {"ok": False, "confirmed": True}):
            with self.subTest(result=result), patch.object(cloud, "_call", return_value=result):
                with self.assertRaises(remote.RemoteError):
                    cloud.logout("synthetic.user", "http://synthetic.invalid")
                self.assertEqual(state.read_text(), "synthetic-state")

    def test_confirmed_logout_clears_auth_state(self):
        state = cloud.state_file("synthetic.user")
        state.write_text("synthetic-state")
        with patch.object(cloud, "_call", return_value={"ok": True, "confirmed": True}):
            self.assertTrue(cloud.logout("synthetic.user", "http://synthetic.invalid")["confirmed"])
        self.assertFalse(state.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
