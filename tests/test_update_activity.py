"""Offline ingress, task inventory and cooperative maintenance tests."""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from modules import proxy_pool, update_activity as activity


class ActivityTests(unittest.TestCase):
    def tearDown(self):
        activity.unfreeze()
        proxy_pool.resume_after_update()

    def test_freeze_drains_started_request_and_rejects_new_requests(self):
        started, release, completed = threading.Event(), threading.Event(), threading.Event()
        class Handler:
            _json = Mock()
            @activity.request_handler
            def execute(self):
                started.set()
                release.wait(2)
                completed.set()
        handler = Handler()
        worker = threading.Thread(target=handler.execute)
        worker.start()
        self.assertTrue(started.wait(1))
        with self.assertRaises(activity.UpdateBusy):
            activity.freeze(timeout=.01)
        release.set()
        worker.join(2)
        self.assertTrue(completed.is_set())
        activity.freeze(timeout=1)
        handler.execute()
        handler._json.assert_called_once()
        self.assertEqual(handler._json.call_args.args[1], 503)
        activity.unfreeze()
        handler.execute()
        self.assertTrue(completed.is_set())

    def test_active_app_thread_or_persisted_intent_blocks_without_network(self):
        release = threading.Event()
        def user_task():
            release.wait(2)
        user_task.__module__ = 'modules.synthetic_task'
        worker = threading.Thread(target=user_task)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            activity.freeze(timeout=0)
            worker.start()
            try:
                with self.assertRaises(activity.UpdateBusy):
                    activity.assert_idle(root)
            finally:
                release.set()
                worker.join(2)
            activity.assert_idle(root)
            pending = root / 'sessions' / 'browser-jobs' / 'fixture'
            pending.mkdir(parents=True)
            (pending / 'fixture.state').write_text('private pending fixture')
            with self.assertRaises(activity.UpdateBusy):
                activity.assert_idle(root)
            (pending / 'fixture.state').unlink()
            registrations = root / 'registration'
            registrations.mkdir()
            record = registrations / 'current.json'
            record.write_text(json.dumps({'status': 'running'}))
            with self.assertRaises(activity.UpdateBusy):
                activity.assert_idle(root)
            record.write_text(json.dumps({'status': 'complete', 'account_saved': True}))
            activity.assert_idle(root)
            edits = root / 'profile-edits'
            edits.mkdir()
            receipt = edits / 'current.json'
            receipt.write_text(json.dumps({'reconciled': False}))
            with self.assertRaises(activity.UpdateBusy):
                activity.assert_idle(root)
            receipt.write_text(json.dumps({'reconciled': True}))
            activity.assert_idle(root)
            receipt.write_text(json.dumps({'reconciled': False, 'result': {'verdict': 'rejected'}}))
            activity.assert_idle(root)
            receipt.write_text(json.dumps({'reconciled': 'true', 'result': {'verdict': 'unknown'}}))
            with self.assertRaises(activity.UpdateBusy):
                activity.assert_idle(root)

    def test_maintenance_parks_after_work_and_resumes_without_losing_work(self):
        work_started, complete_work, finished, stop = [threading.Event() for _ in range(4)]
        def maintenance():
            work_started.set()
            complete_work.wait(2)
            finished.set()
            while not stop.is_set():
                proxy_pool._maintenance_checkpoint()
                proxy_pool._maintenance_pause.wait(.01)
        worker = threading.Thread(target=maintenance)
        with patch.object(proxy_pool, '_auto', worker), patch.object(proxy_pool, '_watch', None):
            worker.start()
            try:
                self.assertTrue(work_started.wait(1))
                self.assertFalse(proxy_pool.pause_for_update(timeout=.01))
                self.assertFalse(proxy_pool.maintenance_quiescent(worker))
                self.assertFalse(finished.is_set())
                complete_work.set()
                self.assertTrue(proxy_pool.pause_for_update(timeout=1))
                self.assertTrue(finished.is_set())
                self.assertTrue(proxy_pool.maintenance_quiescent(worker))
                with patch.object(proxy_pool, '_auto', None), patch.object(proxy_pool.threading, 'Thread', side_effect=AssertionError('new maintenance')):
                    proxy_pool._ensure_auto_check()
                    proxy_pool._ensure_watch()
                proxy_pool.resume_after_update()
                deadline = time.monotonic() + 1
                while proxy_pool.maintenance_quiescent(worker) and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertFalse(proxy_pool.maintenance_quiescent(worker))
            finally:
                stop.set()
                complete_work.set()
                proxy_pool.resume_after_update()
                worker.join(2)
            self.assertFalse(worker.is_alive())
