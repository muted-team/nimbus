"""Offline app lifecycle regressions; native UI and backend are replaced."""
import builtins
import importlib.util
import os
import socket
import json
import http.client
import tempfile
from pathlib import Path
import sys
import types
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_app():
    # Import the complete entry point, without loading a GUI toolkit.
    spec = importlib.util.spec_from_file_location("app_under_test", ROOT / "app.py")
    app = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"webview": types.ModuleType("webview")}):
        spec.loader.exec_module(app)
    return app


class PlatformTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "linux", "Linux process image path")
    def test_compiled_linux_uses_process_image_instead_of_reported_python(self):
        app = load_app()
        expected = Path("/proc/self/exe").readlink()
        missing = str(expected.parent / "missing-embedded-python")
        with patch.object(app, "__compiled__", object(), create=True), patch.object(sys, "executable", missing):
            self.assertEqual(app._runtime_executable(), expected)

    def test_compiled_windows_uses_unicode_image_path_and_rejects_truncation(self):
        app = load_app()
        executable = str(Path.cwd() / "Nimbus Ж 目录" / "Nimbus-runtime.exe")

        def get_image(module, buffer, size):
            buffer.value = executable
            return len(executable)

        get_module_name = Mock(side_effect=get_image)
        dll = types.SimpleNamespace(kernel32=types.SimpleNamespace(GetModuleFileNameW=get_module_name))
        with (patch.object(app, "__compiled__", object(), create=True), patch.object(sys, "platform", "win32"),
              patch.object(app.ctypes, "windll", dll, create=True)):
            self.assertEqual(app._runtime_executable(), Path(executable))
            get_module_name.side_effect = lambda module, buffer, size: size
            with self.assertRaises(OSError):
                app._runtime_executable()

    @unittest.skipIf(sys.platform == "win32", "Linux socket reuse semantics")
    def test_linux_port_probe_reuses_closed_connection_but_rejects_active_listener(self):
        app = load_app()
        listener = socket.socket()
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        client = socket.create_connection(("127.0.0.1", port))
        accepted, _ = listener.accept()
        self.assertFalse(app._port_free(port, "127.0.0.1"))
        accepted.shutdown(socket.SHUT_RDWR)
        accepted.close()
        client.close()
        listener.close()
        self.assertTrue(app._port_free(port, "127.0.0.1"))

    def test_linux_wayland_session_uses_working_x11_webview_backend(self):
        with patch.dict(os.environ, {}, clear=True):
            app = load_app()
        env = {"DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-1", "GDK_BACKEND": "wayland,x11,*"}
        app._configure_linux_webview(env, "linux")
        self.assertEqual(env["GDK_BACKEND"], "x11")
        self.assertEqual(env["WEBKIT_DISABLE_COMPOSITING_MODE"], "1")
        self.assertEqual(env["WEBKIT_DISABLE_DMABUF_RENDERER"], "1")

    def test_webview_configuration_preserves_explicit_backend_and_other_platforms(self):
        with patch.dict(os.environ, {}, clear=True):
            app = load_app()
        for env, platform in (({"DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-1", "GDK_BACKEND": "wayland"}, "linux"),
                              ({"DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-1"}, "win32"),
                              ({"WAYLAND_DISPLAY": "wayland-1"}, "linux")):
            original = dict(env)
            app._configure_linux_webview(env, platform)
            self.assertEqual(env, original)

    def test_windows_webview2_simulation(self):
        app = load_app()
        platforms = types.ModuleType("webview.platforms")
        with patch.object(sys, "platform", "win32"), patch.dict(sys.modules, {"webview.platforms": platforms}):
            for chromium in (True, False):
                platforms.winforms = types.SimpleNamespace(is_chromium=chromium)
                self.assertEqual(app._webview2_missing(), not chromium)
            del platforms.winforms
            self.assertTrue(app._webview2_missing())

    def test_windows_messagebox_simulation(self):
        app = load_app()
        message = Mock(return_value=1)
        dll = types.SimpleNamespace(user32=types.SimpleNamespace(MessageBoxW=message))
        with patch.object(sys, "platform", "win32"), patch.object(app.ctypes, "windll", dll, create=True):
            app._msgbox("test", "title")
        message.assert_called_once_with(0, "test", "title", 0x40)

    def test_linux_does_not_import_winforms(self):
        app = load_app()
        original = builtins.__import__
        attempted = []

        def guarded(name, *args, **kwargs):
            if name == "webview.platforms":
                attempted.append(name)
                raise ImportError("Windows unavailable")
            return original(name, *args, **kwargs)

        with patch.object(sys, "platform", "linux"), patch("builtins.__import__", guarded):
            self.assertFalse(app._webview2_missing())
        self.assertEqual(attempted, [])


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.app = load_app()
        self.httpd = Mock(server_address=("127.0.0.1", 8740))
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        server = types.ModuleType("main")
        server.config = {"port": 8740}
        server.build_server = Mock(return_value=self.httpd)
        auth = types.ModuleType("modules.auth")
        auth.enabled = Mock(return_value=False)
        self.server_mod = server
        self.auth = auth
        self.stack.enter_context(patch.dict(sys.modules, {"main": server, "modules.auth": auth}))
        import modules
        self.stack.enter_context(patch.object(modules, 'auth', auth, create=True))
        self.stack.enter_context(patch.object(sys, "argv", ["app.py"]))
        self.stack.enter_context(patch.object(sys, "platform", "linux"))
        for name in ("_carry_over", "_log"):
            self.stack.enter_context(patch.object(self.app, name))
        self.stack.enter_context(patch.object(self.app, "_port_free", return_value=True))
        self.stack.enter_context(patch.object(self.app.threading, "Thread"))
        self.stack.enter_context(patch.object(sys.stdin, "isatty", return_value=False))
        event = self.stack.enter_context(patch.object(self.app.threading, "Event"))
        event.return_value.wait.side_effect = AssertionError("unexpected headless wait")
        self.open = self.stack.enter_context(patch.object(self.app.webbrowser, "open", return_value=True))
        self.app.webview.create_window = Mock(side_effect=RuntimeError("native unavailable"))
        self.app.webview.start = Mock()
        # Even fatal-error dialogs must never load the real native toolkit.
        self.gtk(False)

    def assert_alive(self):
        self.httpd.shutdown.assert_not_called()
        self.httpd.server_close.assert_not_called()

    def assert_closed_once(self):
        self.httpd.shutdown.assert_called_once_with()
        self.httpd.server_close.assert_called_once_with()

    def gtk(self, available=True):
        gtk = Mock()
        gtk.init_check.return_value = (available, [])
        gi = types.ModuleType("gi")
        gi.require_version = Mock()
        repository = types.ModuleType("gi.repository")
        repository.Gtk = gtk
        self.stack.enter_context(patch.dict(sys.modules, {"gi": gi, "gi.repository": repository}))
        return gtk

    def test_linux_gtk_keeps_backend_until_dialog_completion(self):
        gtk = self.gtk()
        observed = []
        gtk.MessageDialog.return_value.run.side_effect = lambda: observed.append(
            (self.httpd.shutdown.call_count, self.httpd.server_close.call_count))
        self.assertEqual(self.app.main(), 0)
        self.assertEqual(observed, [(0, 0)])
        gtk.MessageDialog.return_value.run.assert_called_once_with()
        gtk.MessageDialog.return_value.destroy.assert_called_once_with()
        self.assert_closed_once()

    def test_gtk_error_destroys_dialog_and_waits_in_terminal(self):
        gtk = self.gtk()
        gtk.MessageDialog.return_value.run.side_effect = RuntimeError("dialog failed")
        self.stack.enter_context(patch.object(sys.stdin, "isatty", return_value=True))
        with patch("builtins.input", side_effect=lambda *a: self.assert_alive()) as prompt:
            self.assertEqual(self.app.main(), 0)
        prompt.assert_called_once()
        gtk.MessageDialog.return_value.destroy.assert_called_once_with()
        self.assert_closed_once()

    def test_gtk_interrupt_destroys_dialog_and_closes_backend(self):
        gtk = self.gtk()
        gtk.MessageDialog.return_value.run.side_effect = KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            self.app.main()
        gtk.MessageDialog.return_value.destroy.assert_called_once_with()
        self.assert_closed_once()

    def test_missing_toolkit_waits_for_terminal_completion(self):
        self.stack.enter_context(patch.dict(sys.modules, {"gi": None}))
        self.stack.enter_context(patch.object(sys.stdin, "isatty", return_value=True))
        with patch("builtins.input", side_effect=lambda *a: self.assert_alive()) as prompt:
            self.assertEqual(self.app.main(), 0)
        prompt.assert_called_once()
        self.assert_closed_once()

    def test_terminal_completion_without_gui(self):
        self.gtk(False)
        self.stack.enter_context(patch.object(sys.stdin, "isatty", return_value=True))
        with patch("builtins.input", side_effect=lambda *a: self.assert_alive()) as prompt:
            self.assertEqual(self.app.main(), 0)
        prompt.assert_called_once()
        self.assert_closed_once()

    def test_headless_wait_is_interruptible_and_keeps_backend(self):
        self.gtk(False)
        self.stack.enter_context(patch.object(sys.stdin, "isatty", return_value=False))

        def interrupt(*args):
            self.assert_alive()
            raise KeyboardInterrupt

        with patch.object(self.app.threading, "Event") as event:
            event.return_value.wait.side_effect = interrupt
            with self.assertRaises(KeyboardInterrupt):
                self.app.main()
            event.return_value.wait.assert_called_once_with(1)
        self.assert_closed_once()

    def test_terminal_eof_does_not_finish_backend(self):
        self.gtk(False)
        self.stack.enter_context(patch.object(sys.stdin, "isatty", return_value=True))
        with patch("builtins.input", side_effect=EOFError), patch.object(self.app.threading, "Event") as event:
            event.return_value.wait.side_effect = KeyboardInterrupt
            with self.assertRaises(KeyboardInterrupt):
                self.app.main()
        self.assert_closed_once()

    def test_closed_stdin_waits_for_interrupt(self):
        self.stack.enter_context(patch.object(sys.stdin, "isatty", side_effect=ValueError("closed")))
        with patch.object(self.app.threading, "Event") as event:
            event.return_value.wait.side_effect = KeyboardInterrupt
            with self.assertRaises(KeyboardInterrupt):
                self.app.main()
        self.assert_closed_once()

    def test_browser_failure_reports_error_and_cleans_once(self):
        for failure in (False, OSError("browser unavailable")):
            with self.subTest(failure=type(failure).__name__):
                self.httpd.reset_mock()
                self.open.side_effect = failure if isinstance(failure, Exception) else None
                self.open.return_value = False
                with self.assertRaisesRegex(RuntimeError, "браузер"):
                    self.app.main()
                self.assert_closed_once()

    def test_missing_webview_branch_also_owns_cleanup(self):
        with patch.object(self.app, "_webview2_missing", return_value=True), patch.object(self.app, "_msgbox", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.app.main()
        self.assert_closed_once()

    def test_missing_webview_normal_completion_cleans_once(self):
        self.gtk()
        with patch.object(self.app, "_webview2_missing", return_value=True):
            self.assertEqual(self.app.main(), 0)
        self.assert_closed_once()

    def test_cleanup_closes_socket_even_if_shutdown_raises(self):
        self.app.webview.create_window.side_effect = None
        self.httpd.shutdown.side_effect = RuntimeError("shutdown failed")
        with self.assertRaisesRegex(RuntimeError, "shutdown failed"):
            self.app.main()
        self.assert_closed_once()

    def test_native_window_normal_and_interrupted_cleanup(self):
        self.app.webview.create_window.side_effect = None
        self.assertEqual(self.app.main(), 0)
        self.assert_closed_once()
        self.httpd.reset_mock()
        self.app.webview.start.side_effect = KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            self.app.main()
        self.assert_closed_once()

    def test_legacy_wildcard_default_does_not_expose_native_app_after_password_is_set(self):
        self.server_mod.config['host'] = '0.0.0.0'
        self.auth.enabled.return_value = True
        self.app.webview.create_window.side_effect = None
        self.assertEqual(self.app.main(), 0)
        self.server_mod.build_server.assert_called_once_with(8740, '127.0.0.1', auth=True)

    def test_fresh_default_wildcard_stays_on_loopback_without_password(self):
        self.server_mod.config.update(host='0.0.0.0', phone_access=False)
        self.app.webview.create_window.side_effect = None
        self.assertEqual(self.app.main(), 0)
        self.server_mod.build_server.assert_called_once_with(8740, '127.0.0.1', auth=True)
        self.httpd.set_phone_access.assert_not_called()

    def test_explicit_wildcard_bind_is_applied_and_window_stays_on_loopback(self):
        self.server_mod.config.update(host='0.0.0.0', bind_explicit=True, phone_access=True)
        self.auth.enabled.return_value = True
        self.httpd.server_address = ('0.0.0.0', 8740)
        self.app.webview.create_window.side_effect = None
        self.assertEqual(self.app.main(), 0)
        self.server_mod.build_server.assert_called_once_with(8740, '0.0.0.0', auth=True)
        self.httpd.set_phone_access.assert_not_called()
        self.assertEqual(self.app.webview.create_window.call_args.args[1], 'http://127.0.0.1:8740')

    def test_explicit_remote_bind_without_password_is_refused_before_any_listener(self):
        self.server_mod.config.update(host='0.0.0.0', bind_explicit=True)
        self.app.webview.create_window.side_effect = None
        with patch.object(self.app, '_fatal_messagebox') as message:
            self.assertEqual(self.app.main(), 1)
        self.server_mod.build_server.assert_not_called()
        self.app.webview.create_window.assert_not_called()
        message.assert_called_once()

    def test_explicit_local_bind_keeps_separate_password_protected_phone_listener(self):
        self.server_mod.config.update(host='127.0.0.1', bind_explicit=True, phone_access=True)
        self.auth.enabled.return_value = True
        self.app.webview.create_window.side_effect = None
        self.assertEqual(self.app.main(), 0)
        self.server_mod.build_server.assert_called_once_with(8740, '127.0.0.1', auth=True)
        self.httpd.set_phone_access.assert_called_once_with(True)

    def test_explicit_localhost_is_normalized_to_reachable_loopback_without_password(self):
        self.server_mod.config.update(host='localhost', bind_explicit=True)
        self.app.webview.create_window.side_effect = None
        self.assertEqual(self.app.main(), 0)
        self.server_mod.build_server.assert_called_once_with(8740, '127.0.0.1', auth=True)

    def test_explicit_specific_network_address_opens_the_window_on_the_actual_listener(self):
        self.server_mod.config.update(host='192.168.1.5', bind_explicit=True)
        self.auth.enabled.return_value = True
        self.httpd.server_address = ('192.168.1.5', 8740)
        self.app.webview.create_window.side_effect = None
        self.assertEqual(self.app.main(), 0)
        self.server_mod.build_server.assert_called_once_with(8740, '192.168.1.5', auth=True)
        self.assertEqual(self.app.webview.create_window.call_args.args[1], 'http://192.168.1.5:8740')

    def test_invalid_ipv4_startup_bind_is_refused_before_port_probe_or_server(self):
        self.auth.enabled.return_value = True
        for host in ('::', '2001:db8::1', 'http://127.0.0.1', '192.168.001.5', '127.1'):
            with self.subTest(host=host), patch.object(self.app, '_fatal_messagebox') as message:
                self.server_mod.config.update(host=host, bind_explicit=True)
                self.assertEqual(self.app.main(), 1)
                message.assert_called_once()
        self.server_mod.build_server.assert_not_called()
        self.app._port_free.assert_not_called()

    def test_occupied_highest_port_never_probes_outside_tcp_port_range(self):
        self.server_mod.config['port'] = 65535
        def occupied(port, host):
            self.assertLessEqual(port, 65535, 'Startup attempted an invalid TCP port')
            return False
        self.app._port_free.side_effect = occupied
        with patch.object(self.app, '_fatal_messagebox') as message:
            self.assertEqual(self.app.main(), 1)
        self.app._port_free.assert_called_once_with(65535, '127.0.0.1')
        self.server_mod.build_server.assert_not_called()
        self.assertNotIn('65554', message.call_args.args[0])

    def test_busy_penultimate_port_can_use_the_last_valid_port(self):
        self.server_mod.config['port'] = 65534
        self.app._port_free.side_effect = lambda port, host: port == 65535
        self.httpd.server_address = ('127.0.0.1', 65535)
        self.app.webview.create_window.side_effect = None
        self.assertEqual(self.app.main(), 0)
        self.server_mod.build_server.assert_called_once_with(65535, '127.0.0.1', auth=True)

    def test_out_of_range_configured_port_is_refused_before_socket_probe(self):
        self.server_mod.config['port'] = 65536
        with patch.object(self.app, '_fatal_messagebox') as message:
            self.assertEqual(self.app.main(), 1)
            message.assert_called_once()
        self.app._port_free.assert_not_called()


class NetworkStartupHttpTests(unittest.TestCase):
    def test_explicit_wildcard_startup_uses_real_socket_and_password_gated_api(self):
        from modules import config, auth
        from tests.test_phone_access import server_class, application_handler
        app = load_app()
        with tempfile.TemporaryDirectory() as tmp, patch.object(config, 'CONFIG_FILE', Path(tmp) / 'config.json'):
            config.write_text_atomic(config.CONFIG_FILE,
                                     '{"host":"0.0.0.0","bind_explicit":true,"port":8740,"phone_access":true}')
            auth.set_password('synthetic-startup-password')
            backend = types.ModuleType('main')
            backend.config = config
            servers = []
            def build(port, host, auth=True):
                self.assertEqual(host, '0.0.0.0')
                instance = server_class()((host, 0), application_handler())
                instance.require_auth = auth
                instance.daemon_threads = True
                servers.append(instance)
                return instance
            backend.build_server = build
            def request(source='127.0.0.1', path='/api/settings', method='GET', body=None, cookie=None):
                connection = http.client.HTTPConnection('127.0.0.1', servers[0].server_port,
                                                       source_address=(source, 0), timeout=3)
                headers = {'Content-Type': 'application/json'}
                if cookie: headers['Cookie'] = cookie
                connection.request(method, path, json.dumps(body) if body is not None else None, headers)
                response = connection.getresponse()
                result = response.status, json.loads(response.read()), response.getheader('Set-Cookie')
                connection.close()
                return result
            def native_start(**kwargs):
                status, settings, _ = request()
                self.assertEqual(status, 200)
                self.assertEqual(settings['bound']['host'], '0.0.0.0')
                self.assertTrue(settings['phone']['active'])
                self.assertFalse(settings['phone']['supported'])
                self.assertIs(settings['phone'].get('connected'), False)
                self.assertEqual(servers[0]._phone_servers, [])
                self.assertEqual(request('127.0.0.2')[0], 401)
                status, _, cookie = request('127.0.0.2', '/api/auth', 'POST', {'password': 'synthetic-startup-password'})
                self.assertEqual(status, 200)
                self.assertEqual(request('127.0.0.2', cookie=cookie)[0], 200)
                self.assertIs(request()[1]['phone'].get('connected'), True)
                auth.clear_password()
                self.assertEqual(request('127.0.0.2', cookie=cookie)[0], 401)
            app.webview.create_window = Mock()
            app.webview.start = native_start
            with (patch.dict(sys.modules, {'main': backend}), patch.object(sys, 'argv', ['app.py']),
                  patch.object(app, '_carry_over'), patch.object(app, '_log'),
                  patch.object(app, '_browser_fallback', side_effect=AssertionError('Unexpected fallback in headless test')),
                  patch.object(app, '_fatal_messagebox', side_effect=AssertionError('Unexpected native dialog in headless test')),
                  patch.object(app, '_port_free', return_value=True), patch.object(app, '_webview2_missing', return_value=False)):
                self.assertEqual(app.main(), 0)
            self.assertEqual(app.webview.create_window.call_args.args[1], f'http://127.0.0.1:{servers[0].server_port}')
            self.assertEqual(servers[0].fileno(), -1)


if __name__ == "__main__":
    unittest.main()
