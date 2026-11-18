"""No GUI/process launch: native bridge handoff only uses synthetic collaborators."""
from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch

from tests.test_app_platform import load_app
from modules import proxy_pool, update_activity
from modules.client_updates import UpdateError


class BridgeTests(unittest.TestCase):
    def tearDown(self):
        update_activity.unfreeze()
        proxy_pool.resume_after_update()

    def fixture(self, temporary):
        app = load_app()
        app._BOOTSTRAP_GUARD = object()
        app.webview.windows = [Mock()]
        root, stage = Path(temporary), Path(temporary) / 'stage'
        stage.mkdir()
        updater = Mock()
        updater.lock = threading.Lock()
        updater._exclusive.side_effect = lambda: updater.lock.acquire()
        updater.activation_digest.return_value = 'f' * 64
        updater.activation_arguments.return_value = tuple(map(str, (root, stage, '1.0.1')))
        api = app.Api()
        api._client_updater = Mock(return_value=updater)
        return app, api, updater

    def test_ready_helper_precedes_window_close_and_only_one_handoff(self):
        with tempfile.TemporaryDirectory() as temporary:
            app, api, updater = self.fixture(temporary)
            process = Mock()
            process.poll.return_value = None
            def popen(command, **options):
                self.assertTrue(options['close_fds'])
                self.assertEqual(command[0], app.sys.executable)
                self.assertEqual(command[1], '--activate-runtime')
                Path(command[-1]).write_bytes(b'ready\n')
                return process
            timer = Mock()
            with patch('subprocess.Popen', side_effect=popen) as spawn, patch.object(app.threading, 'Timer', return_value=timer) as schedule, patch.object(update_activity, 'assert_idle'), patch.object(proxy_pool, 'pause_for_update', return_value=True):
                self.assertEqual(api.restart_client_update(), {'ok': True})
                app.webview.windows[0].destroy.assert_not_called()
                self.assertIn('error', api.restart_client_update())
                self.assertEqual(spawn.call_count, 1)
                schedule.call_args.args[1]()
                app.webview.windows[0].destroy.assert_called_once()
            self.assertFalse(updater.lock.locked())
            process.terminate.assert_not_called()

    def test_busy_or_invalid_stage_preserves_window_and_does_not_spawn(self):
        for invalid_stage in (False, True):
            with self.subTest(invalid_stage=invalid_stage), tempfile.TemporaryDirectory() as temporary:
                app, api, updater = self.fixture(temporary)
                if invalid_stage:
                    updater.activation_arguments.side_effect = UpdateError('invalid verified stage')
                with patch('subprocess.Popen') as spawn, patch.object(update_activity, 'assert_idle', side_effect=update_activity.UpdateBusy('user task running')), patch.object(proxy_pool, 'pause_for_update', return_value=True), patch.object(proxy_pool, 'resume_after_update') as resume:
                    self.assertIn('error', api.restart_client_update())
                    spawn.assert_not_called()
                    app.webview.windows[0].destroy.assert_not_called()
                    if not invalid_stage:
                        resume.assert_called_once()
                self.assertFalse(updater.lock.locked())
                update_activity.freeze(timeout=0)
                update_activity.unfreeze()

    def test_exited_helper_preserves_window_and_reopens_ingress(self):
        with tempfile.TemporaryDirectory() as temporary:
            app, api, updater = self.fixture(temporary)
            process = Mock()
            process.poll.return_value = 1
            with patch('subprocess.Popen', return_value=process), patch.object(update_activity, 'assert_idle'), patch.object(proxy_pool, 'pause_for_update', return_value=True), patch.object(proxy_pool, 'resume_after_update') as resume:
                self.assertIn('error', api.restart_client_update())
                app.webview.windows[0].destroy.assert_not_called()
                resume.assert_called_once()
            self.assertFalse(updater.lock.locked())
            update_activity.freeze(timeout=0)

    def test_failed_window_close_cancels_armed_helper_before_resuming(self):
        with tempfile.TemporaryDirectory() as temporary:
            app, api, _ = self.fixture(temporary)
            process = Mock()
            process.poll.return_value = None
            app.webview.windows[0].destroy.side_effect = RuntimeError('window did not close')
            def popen(command, **options):
                Path(command[-1]).write_bytes(b'ready\n')
                return process
            with (patch('subprocess.Popen', side_effect=popen),
                  patch.object(app.threading, 'Timer') as schedule,
                  patch.object(update_activity, 'assert_idle'),
                  patch.object(proxy_pool, 'pause_for_update', return_value=True),
                  patch.object(proxy_pool, 'resume_after_update') as resume):
                resume.side_effect = lambda: process.wait.assert_called_once_with(timeout=5)
                self.assertEqual(api.restart_client_update(), {'ok': True})
                schedule.call_args.args[1]()
                process.terminate.assert_called_once()
                resume.assert_called_once()
                self.assertFalse(api._restart_requested)
