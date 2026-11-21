import unittest
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from modules import client_device, execution, remote
from modules.browser_states import BrowserStates


class ExecutionTests(unittest.TestCase):
    def test_negotiation_is_per_operation_and_fails_closed(self):
        raw = {"operations": {"login": [
            {"mode": 3, "supported": True, "available": True},
            {"mode": 4, "supported": True, "available": False},
            {"mode": 2, "supported": True, "available": True}],
            "publish": [{"mode": 3, "supported": True, "available": "yes"}]}}
        with patch.object(remote, "request", return_value=raw):
            ops = execution.capabilities()["operations"]
        self.assertEqual([r["mode"] for r in ops["login"] if r["available"]], [3])
        self.assertFalse(any(r["available"] for r in ops["publish"]))
        self.assertFalse(any(r["available"] for r in ops["logout"]))

    def test_failed_or_duplicate_negotiation_never_sends_mutation(self):
        for response in (None, {}, {"operations": {"login": [
                {"mode": 3, "supported": True, "available": True}] * 2}}):
            with self.subTest(response=response), patch.object(remote, "request", return_value=response) as request:
                with self.assertRaises(execution.ExecutorUnavailable):
                    execution.execute("login", 3, {"username": "fixture.user"})
                self.assertEqual(request.call_count, 1)
        with patch.object(remote, "request", side_effect=remote.RemoteError("offline")) as request:
            with self.assertRaises(execution.ExecutorUnavailable):
                execution.execute("login", 3, {})
            self.assertEqual(request.call_count, 1)

    def test_explicit_mode_has_exact_route_and_no_retry(self):
        caps = {"operations": {"logout": [{"mode": 4, "supported": True, "available": True}]}}
        with patch.object(remote, "request", side_effect=[caps, {"job_id": "synthetic-job", "operation": "logout", "mode": 4}]) as request:
            self.assertEqual(execution.execute("logout", 4, {"browser_state": "synthetic-state"})["job_id"], "synthetic-job")
            request.assert_called_with("POST", "/v3/browser/logout", json={"mode": 4, "browser_state": "synthetic-state"},
                                       timeout=(10, 80), retry_busy=False)

    def test_invalid_mode_cannot_fall_back_or_override(self):
        with patch.object(remote, "request") as request:
            for mode in (None, True, "3", 1, 2):
                with self.assertRaises(execution.ExecutorUnavailable):
                    execution.execute("login", mode, {})
            with self.assertRaises(ValueError):
                execution.execute("login", 3, {"mode": 4})
            request.assert_not_called()

    def test_browser_mutations_are_protected(self):
        for operation in execution.OPERATIONS:
            self.assertTrue(remote._protected("POST", execution.ROOT + "/" + operation))
        self.assertTrue(remote._protected("POST", execution.ROOT + "/jobs/synthetic-job/cancel"))

    def test_cancel_disables_redirects_at_transport_boundary(self):
        response = SimpleNamespace(status_code=200, headers={}, json=lambda: {"status": "cancelled"})
        with client_device.use_browser_profile("firefox155"), patch.object(remote, "base", return_value="https://fixture.invalid"), patch.object(
                remote, "key", return_value="synthetic-key"), patch.object(remote, "_send", return_value=response) as send:
            execution.cancel("synthetic-job")
            self.assertIs(send.call_args.kwargs["allow_redirects"], False)

    def test_two_threads_submit_only_one_job_and_busy_call_does_not_wait(self):
        with tempfile.TemporaryDirectory() as temporary:
            def states(kind="browser"):
                return BrowserStates(temporary + "/" + kind, "synthetic-concurrent-namespace")
            polling, release = threading.Event(), threading.Event()
            outcomes = []
            def response(method, path, **kwargs):
                if path.endswith("/capabilities"):
                    return {"operations": {"login": [{"mode": 3, "supported": True, "available": True}]}}
                if method == "POST":
                    return {"job_id": "synthetic-job", "operation": "login", "mode": 3}
                polling.set()
                if not release.wait(5):
                    raise AssertionError("Test did not release polling")
                return {"status": "complete", "result": {"ok": True, "verdict": "ok", "uid": "123",
                        "state_owner": "fixture.user", "browser_state": "synthetic-new-state"}}
            def run():
                try:
                    outcomes.append(execution.run_account("login", 3, "fixture.user", None))
                except Exception as exc:
                    outcomes.append(exc)
            with patch.object(execution, "store", side_effect=states), patch.object(remote, "request", side_effect=response) as request:
                first = threading.Thread(target=run)
                second = threading.Thread(target=run)
                first.start()
                try:
                    self.assertTrue(polling.wait(2))
                    second.start()
                    second.join(1)
                    self.assertFalse(second.is_alive(), "Busy request must reject before the first request finishes")
                    self.assertTrue(any(isinstance(out, execution.ExecutorUnavailable) for out in outcomes))
                finally:
                    release.set()
                    first.join(2)
                    if second.ident is not None:
                        second.join(2)
                self.assertFalse(first.is_alive())
                self.assertEqual(sum(call.args[0] == "POST" for call in request.call_args_list), 1)
                self.assertTrue(any(isinstance(out, dict) and out.get("ok") for out in outcomes))

    def test_login_requires_positive_uid_before_saving_any_auth_state(self):
        for uid in (None, "", "0", 0, -1, True, "1.5", 1.5, "abc", "1" * 65):
            with self.subTest(uid=uid), tempfile.TemporaryDirectory() as temporary:
                def states(kind="browser"):
                    return BrowserStates(temporary + "/" + kind, "synthetic-uid-namespace")
                states().write("fixture.user", 3, "synthetic-old-browser")
                states("browser-companion").write("fixture.user", 3, "synthetic-old-companion")
                result = {"ok": True, "verdict": "ok", "uid": uid, "state_owner": "fixture.user",
                          "browser_state": "synthetic-new-browser", "state": "synthetic-new-companion"}
                with patch.object(execution, "store", side_effect=states), patch.object(execution, "execute", return_value={
                        "job_id": "synthetic-job", "operation": "login", "mode": 3}), patch.object(execution, "job", return_value={
                            "status": "complete", "result": result}):
                    with self.assertRaises(remote.RemoteError):
                        execution.run_account("login", 3, "fixture.user", None)
                self.assertEqual(states().read("fixture.user", 3), "synthetic-old-browser")
                self.assertEqual(states("browser-companion").read("fixture.user", 3), "synthetic-old-companion")

    def test_pending_job_resumes_without_resubmitting_or_losing_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            def states(kind="browser"):
                return BrowserStates(temporary + "/" + kind, "synthetic-namespace")
            states().write("fixture.user", 3, "synthetic-browser-state")
            result = {"ok": False, "verdict": "unknown", "state_owner": "fixture.user"}
            with patch.object(execution, "store", side_effect=states), patch.object(execution, "execute", return_value={
                    "job_id": "synthetic-job", "operation": "publish", "mode": 3}) as submit, patch.object(
                        execution, "job", return_value={"status": "interrupted_or_unknown", "result": result}):
                self.assertTrue(execution.run_account("publish", 3, "fixture.user", None)["stop_account"])
                self.assertTrue(execution.run_account("publish", 3, "fixture.user", None)["stop_account"])
                self.assertEqual(submit.call_count, 1)
            self.assertEqual(states().read("fixture.user", 3), "synthetic-browser-state")

    def test_unacknowledged_dispatch_cannot_send_credentials_twice(self):
        with tempfile.TemporaryDirectory() as temporary:
            def states(kind="browser"):
                return BrowserStates(temporary + "/" + kind, "synthetic-namespace")
            def submit(*args, **kwargs):
                kwargs["before_submit"]()
                raise remote.RemoteError("synthetic timeout", outcome_unknown=True)
            with patch.object(execution, "store", side_effect=states), patch.object(execution, "execute", side_effect=submit) as send:
                with self.assertRaises(remote.RemoteError):
                    execution.run_account("login", 3, "fixture.user", None, password="synthetic-password")
                with self.assertRaises(execution.ExecutorUnavailable):
                    execution.run_account("login", 3, "fixture.user", None, password="synthetic-password")
                self.assertEqual(send.call_count, 1)
                self.assertNotIn("synthetic-password", states("browser-jobs").read("fixture.user", 3))

    def test_public_browser_publish_is_rejected_before_mutation(self):
        caps = {"operations": {"publish": [{"mode": 3, "supported": True, "available": True}]}}
        with patch.object(remote, "request", return_value=caps) as request:
            with self.assertRaises(ValueError):
                execution.execute("publish", 3, {"visibility": "public"})
            self.assertEqual(request.call_count, 1)

    def test_explicit_browser_route_skips_legacy_firefox_remap_and_handshake(self):
        response = SimpleNamespace(status_code=202, headers={}, json=lambda: {
            "job_id": "synthetic-job", "mode": 3, "operation": "login"})
        with client_device.use_browser_profile("firefox155"), patch.object(remote, "base", return_value="https://fixture.invalid"), patch.object(
                remote, "key", return_value="synthetic-key"), patch.object(remote, "_send", return_value=response) as send, patch.object(
                    remote, "_ensure_browser_profile") as handshake:
            out = remote.request("POST", "/v3/browser/login", json={"username": "fixture.user"})
            self.assertEqual(out["job_id"], "synthetic-job")
            self.assertEqual(send.call_args.args[:2], ("POST", "https://fixture.invalid/v3/browser/login"))
            handshake.assert_not_called()

    def test_main_browser_logout_does_not_clear_http_session(self):
        import main
        from modules import accounts, cloud, proxy_pool
        handler = main.Handler.__new__(main.Handler)
        handler._read_json = lambda: ({"username": "fixture.user"}, None)
        handler._campaign_running = lambda: False
        replies = []
        handler._json = lambda response, *args: replies.append(response)
        lease = SimpleNamespace(url="http://synthetic.invalid", release=lambda: None)
        with patch.object(proxy_pool, "lease", return_value=lease), patch.object(cloud, "logout", return_value={
                "ok": True, "confirmed": True, "browser_mode": 3}), patch.object(accounts, "clear_session") as clear:
            handler._api_accounts_logout()
            clear.assert_not_called()
            self.assertTrue(replies[0]["confirmed"])

    def test_unavailable_publish_preserves_consumable_media_before_admission(self):
        from modules import config, photo_source, uniq
        with tempfile.TemporaryDirectory() as temporary:
            media = Path(temporary) / "synthetic.jpg"
            media.write_bytes(b"synthetic-original-media")
            cfg = {"execution_modes": {"publish": 3}, "browser_visibility": "private"}
            with patch.object(config, "get", side_effect=lambda key, default=None: cfg.get(key, default)), patch.object(
                    uniq, "render_file", return_value=b"synthetic-rendered-media"), patch.object(
                        remote, "request", return_value={"operations": {"publish": [{"mode": 3,
                            "supported": True, "available": False, "reason": "synthetic unavailable"}]}}) as request:
                with self.assertRaises(execution.ExecutorUnavailable):
                    photo_source.prepare_post_photos([media], username="fixture.user", consume=True,
                                                     media="photo", via=("fixture.user", None))
                self.assertEqual(media.read_bytes(), b"synthetic-original-media")
                self.assertEqual(list(Path(temporary).iterdir()), [media])
                self.assertEqual(request.call_count, 1)
                self.assertEqual(request.call_args.args[0], "GET")

    def test_main_unavailable_browser_logout_returns_json(self):
        import main
        from modules import cloud, proxy_pool
        handler = main.Handler.__new__(main.Handler)
        handler._read_json = lambda: ({"username": "fixture.user"}, None)
        handler._campaign_running = lambda: False
        replies = []
        handler._json = lambda response, *args: replies.append(response)
        lease = SimpleNamespace(url=None, release=lambda: None)
        with patch.object(proxy_pool, "lease", return_value=lease), patch.object(cloud, "logout",
                side_effect=execution.ExecutorUnavailable("synthetic executor unavailable")):
            handler._api_accounts_logout()
        self.assertFalse(replies[0]["ok"])
        self.assertFalse(replies[0]["confirmed"])
        self.assertEqual(replies[0]["error"], "synthetic executor unavailable")


if __name__ == "__main__":
    unittest.main()
