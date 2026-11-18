"""Synthetic launcher and pointer tests; no desktop or installed client touched."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from modules.bootstrap import (BootstrapError, MARKER, POINTER, RUNTIME_MARKER,
                               activate, enter_runtime, executable_name, selected_runtime, inventory_digest,
                               relaunch_current_if_idle, cleanup_staging, launcher_name)
from modules.update_lock import InstallationBusy

requires_activation_lock = unittest.skipUnless(sys.platform in ('linux', 'win32'),
                                               'Linux or Windows activation lock')


class Crash(BaseException):
    pass


class BootstrapTests(unittest.TestCase):
    def runtime(self, parent, version, content=b'fixture'):
        runtime = parent / ('runtime-v' + version)
        runtime.mkdir()
        executable = runtime / executable_name()
        executable.write_bytes(content)
        executable.chmod(0o755)
        (runtime / RUNTIME_MARKER).write_text(json.dumps({'format': 1, 'version': version}))
        return runtime

    def fixture(self, parent):
        root = parent.resolve() / 'install'
        root.mkdir()
        (root / MARKER).write_text('{"format":1}')
        launcher = root / launcher_name()
        launcher.write_bytes(b'synthetic stable launcher')
        launcher.chmod(0o755)
        (root / 'runtimes').mkdir()
        self.runtime(root / 'runtimes', '1.0.0')
        (root / POINTER).write_bytes(b'runtime-v1.0.0\n')
        staging = parent / 'staging'
        staging.mkdir()
        new = self.runtime(staging, '1.0.1', b'new fixture')
        (root / 'accounts.json').write_bytes(b'private fixture')
        return root, new

    @requires_activation_lock
    def test_crashes_always_select_complete_old_or_new_runtime(self):
        for point in ('validated', 'runtime-visible', 'pointer-ready', 'activated'):
            with self.subTest(point=point), tempfile.TemporaryDirectory() as temporary:
                root, new = self.fixture(Path(temporary))
                def crash(current):
                    if current == point:
                        raise Crash()
                with self.assertRaises(Crash):
                    activate(root, new, '1.0.1', checkpoint=crash)
                expected = 'runtime-v1.0.1' if point == 'activated' else 'runtime-v1.0.0'
                self.assertEqual(selected_runtime(root).name, expected)
                self.assertEqual((root / 'accounts.json').read_bytes(), b'private fixture')
                if point != 'activated':
                    # A freshly verified retry can reuse an identical orphan runtime.
                    if not new.exists():
                        new = self.runtime(Path(temporary) / 'staging', '1.0.1', b'new fixture')
                    activate(root, new, '1.0.1')
                    self.assertEqual(selected_runtime(root).name, 'runtime-v1.0.1')

    @requires_activation_lock
    def test_hard_process_exit_releases_guard_and_preserves_complete_selection(self):
        code = ("import os,sys; from modules.bootstrap import activate; "
                "activate(sys.argv[1],sys.argv[2],'1.0.1', "
                "checkpoint=lambda p: os._exit(77) if p==sys.argv[3] else None)")
        for point in ('runtime-visible', 'pointer-ready', 'activated'):
            with self.subTest(point=point), tempfile.TemporaryDirectory() as temporary:
                root, new = self.fixture(Path(temporary))
                result = subprocess.run([sys.executable, '-c', code, str(root), str(new), point],
                                        cwd=Path(__file__).resolve().parents[1], timeout=10)
                self.assertEqual(result.returncode, 77)
                expected = 'runtime-v1.0.1' if point == 'activated' else 'runtime-v1.0.0'
                runtime = selected_runtime(root)
                self.assertEqual(runtime.name, expected)
                environment = {'NIMBUS_BOOTSTRAP_ROOT': str(root), 'NIMBUS_DATA_ROOT': str(root)}
                guard = enter_runtime(runtime / executable_name(), environment)
                guard.close()

    def test_missing_or_nonexecutable_launcher_never_signals_ready(self):
        cases = ('missing', 'nonexecutable') if sys.platform == 'linux' else ('missing',)
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root, new = self.fixture(Path(temporary))
                launcher = root / launcher_name()
                if case == 'missing':
                    launcher.unlink()
                else:
                    launcher.chmod(0o644)
                ready = []
                with self.assertRaises(BootstrapError):
                    activate(root, new, '1.0.1', ready=lambda: ready.append(True),
                             expected_digest=inventory_digest(new))
                self.assertFalse(ready)
                self.assertEqual(selected_runtime(root).name, 'runtime-v1.0.0')
                self.assertTrue(new.is_dir())
                self.assertEqual((root / 'accounts.json').read_bytes(), b'private fixture')

    @unittest.skipUnless(sys.platform == 'linux', 'Linux executable permission')
    def test_nonexecutable_runtime_never_switches_pointer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, new = self.fixture(Path(temporary))
            executable = new / executable_name()
            executable.chmod(0o644)
            with self.assertRaisesRegex(BootstrapError, 'Staged runtime is not executable'):
                activate(root, new, '1.0.1')
            executable.chmod(0o755)
            orphan = self.runtime(root / 'runtimes', '1.0.1', executable.read_bytes())
            (orphan / executable_name()).chmod(0o644)
            with self.assertRaisesRegex(BootstrapError, 'Target runtime is not executable'):
                activate(root, new, '1.0.1')
            self.assertEqual(selected_runtime(root).name, 'runtime-v1.0.0')

    @requires_activation_lock
    def test_launcher_is_rechecked_after_readiness_under_process_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, new = self.fixture(Path(temporary))
            expected = inventory_digest(new)
            def remove_after_ready():
                (root / launcher_name()).unlink()
            with self.assertRaises(BootstrapError):
                activate(root, new, '1.0.1', ready=remove_after_ready, expected_digest=expected)
            self.assertEqual(selected_runtime(root).name, 'runtime-v1.0.0')
            self.assertTrue(new.is_dir())

    @requires_activation_lock
    def test_known_conflict_never_signals_ready_and_parent_digest_is_enforced(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, new = self.fixture(Path(temporary))
            expected = inventory_digest(new)
            conflict = self.runtime(root / 'runtimes', '1.0.1', b'conflict')
            ready = []
            with self.assertRaises(BootstrapError):
                activate(root, new, '1.0.1', ready=lambda: ready.append(True), expected_digest=expected)
            self.assertFalse(ready)
            shutil.rmtree(conflict)
            def changed_after_ready():
                ready.append(True)
                (new / executable_name()).write_bytes(b'changed after parent verification')
            with self.assertRaises(BootstrapError):
                activate(root, new, '1.0.1', ready=changed_after_ready, expected_digest=expected)
            self.assertEqual(ready, [True])
            self.assertEqual(selected_runtime(root).name, 'runtime-v1.0.0')
            with self.assertRaises(BootstrapError):
                activate(root, new, '1.0.1', ready=lambda: ready.append(True), expected_digest=expected)
            self.assertEqual(ready, [True])

    @unittest.skipUnless(sys.platform == 'linux', 'Synthetic Unix launcher fallback')
    def test_late_helper_failure_relaunches_intact_old_pointer(self):
        from modules.update_lock import InstallationLock
        import time
        repository = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            root, new = self.fixture(Path(temporary))
            old = selected_runtime(root) / executable_name()
            launcher = root / 'Nimbus'
            launcher.write_text('#!/bin/sh\ncat .nimbus-current > fallback.marker\n')
            launcher.chmod(0o755)
            readiness = new.parent / ('.nimbus-activation-ready-' + 'a' * 32)
            arguments = [str(old), '--activate-runtime', str(root), str(new), '1.0.1',
                         inventory_digest(new), str(readiness)]
            code = ('import os,runpy,sys; sys.frozen=True; sys.executable=sys.argv[1]; '
                    'sys.argv=' + repr(arguments) + "; runpy.run_path('app.py',run_name='__main__')")
            guard = InstallationLock(root).acquire()
            helper = subprocess.Popen([sys.executable, '-c', code, str(old)], cwd=repository,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                deadline = time.monotonic() + 5
                while not readiness.exists() and helper.poll() is None and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(readiness.exists())
                self.assertEqual(selected_runtime(root).name, 'runtime-v1.0.0')
                (new / executable_name()).write_bytes(b'changed after readiness')
                guard.close()
                stdout, stderr = helper.communicate(timeout=10)
                self.assertEqual(helper.returncode, 1, stdout + stderr)
                deadline = time.monotonic() + 3
                while not (root / 'fallback.marker').exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertEqual((root / 'fallback.marker').read_bytes(), b'runtime-v1.0.0\n')
                self.assertEqual((root / 'accounts.json').read_bytes(), b'private fixture')
            finally:
                guard.close()
                if helper.poll() is None:
                    helper.kill()
                    helper.communicate()
                helper.stdout.close()
                helper.stderr.close()

    @requires_activation_lock
    def test_cleanup_removes_only_own_download_after_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, new = self.fixture(Path(temporary))
            scratch = root / '.nimbus-update-fixture'
            scratch.mkdir()
            (scratch / 'package.zip').write_bytes(b'public synthetic package')
            package_runtimes = scratch / 'Nimbus v1.0.1' / 'runtimes'
            package_runtimes.mkdir(parents=True)
            staged = package_runtimes / new.name
            new.rename(staged)
            activate(root, staged, '1.0.1')
            self.assertTrue(cleanup_staging(root, staged, '1.0.1'))
            self.assertFalse(scratch.exists())
            self.assertEqual((root / 'accounts.json').read_bytes(), b'private fixture')
            self.assertFalse(cleanup_staging(root, new, '1.0.1'))
            self.assertEqual(selected_runtime(root).name, 'runtime-v1.0.1')

    @requires_activation_lock
    def test_user_data_and_live_sqlite_wal_are_byte_exact(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, new = self.fixture(Path(temporary))
            connection = sqlite3.connect(root / 'data.db')
            try:
                connection.execute('pragma journal_mode=wal')
                connection.execute('create table fixture(value)')
                connection.execute("insert into fixture values ('private')")
                connection.commit()
                names = ('data.db', 'data.db-wal', 'data.db-shm', 'accounts.json')
                before = {name: (root / name).read_bytes() for name in names}
                activate(root, new, '1.0.1')
                self.assertEqual({name: (root / name).read_bytes() for name in names}, before)
                self.assertEqual(connection.execute('select * from fixture').fetchall(), [('private',)])
            finally:
                connection.close()

    @requires_activation_lock
    def test_runtime_owns_lock_and_stale_runtime_refuses_to_start(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, new = self.fixture(Path(temporary))
            old = selected_runtime(root) / executable_name()
            environment = {'NIMBUS_BOOTSTRAP_ROOT': str(root), 'NIMBUS_DATA_ROOT': str(root)}
            guard = enter_runtime(old, environment)
            try:
                with self.assertRaises(InstallationBusy):
                    activate(root, new, '1.0.1', timeout=0)
            finally:
                guard.close()
            activate(root, new, '1.0.1')
            with self.assertRaises(BootstrapError):
                enter_runtime(old, environment)
            with self.assertRaises(BootstrapError):
                enter_runtime(selected_runtime(root) / executable_name(), {})

    def test_packaged_entry_rejects_direct_or_invalid_helper_before_app_imports(self):
        repository = Path(__file__).resolve().parents[1]
        for helper in (False, True):
            with self.subTest(helper=helper), tempfile.TemporaryDirectory() as temporary:
                root, new = self.fixture(Path(temporary))
                executable = selected_runtime(root) / executable_name()
                arguments = ([str(executable), '--activate-runtime', str(root), str(new / 'missing'), '1.0.1']
                             if helper else [str(executable)])
                code = ('import os,runpy,sys,ctypes,types; '
                        'ctypes.windll=types.SimpleNamespace(user32=types.SimpleNamespace(MessageBoxW=lambda *a:1)); '
                        'sys.frozen=True; '
                        'sys.executable=sys.argv[1]; sys.argv=' + repr(arguments) + '; '
                        "os.environ.pop('NIMBUS_BOOTSTRAP_ROOT',None); "
                        "os.environ.pop('NIMBUS_DATA_ROOT',None); "
                        "runpy.run_path('app.py',run_name='__main__')")
                result = subprocess.run([sys.executable, '-c', code, str(executable)],
                                        cwd=repository, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 1)
                self.assertNotIn('webview', result.stderr)
                self.assertFalse((root / 'config.json').exists())
                self.assertFalse((root / 'logs').exists())
                self.assertEqual(selected_runtime(root).name, 'runtime-v1.0.0')

    def test_pointer_escape_and_symlinks_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, new = self.fixture(Path(temporary))
            for value in ('../outside', 'runtime-v1.0.0\nextra', '/tmp/runtime-v1.0.0', 'runtime-v1.0.0\r\n'):
                (root / POINTER).write_bytes(value.encode('ascii'))
                with self.assertRaises(BootstrapError):
                    selected_runtime(root)
            (root / POINTER).write_bytes(b'runtime-v1.0.0\n')
            marker = new / RUNTIME_MARKER
            marker.unlink()
            try:
                marker.symlink_to(root / MARKER)
            except OSError:
                self.skipTest('Creating symlinks requires platform privileges')
            with self.assertRaises(BootstrapError):
                activate(root, new, '1.0.1')

    @unittest.skipUnless(sys.platform == 'win32' and shutil.which('cl'), 'Windows MSVC smoke')
    def test_windows_native_launcher_unicode_shared_root(self):
        with tempfile.TemporaryDirectory(prefix='nimbus-') as temporary:
            parent = Path(temporary) / 'unicode-Ж-目录'
            parent.mkdir()
            root, _ = self.fixture(parent)
            source = Path(__file__).resolve().parents[1] / 'native' / 'bootstrap.cpp'
            runtime_source = parent / 'fixture.cpp'
            runtime_source.write_text("""#include <windows.h>
#include <cwchar>
int WINAPI wWinMain(HINSTANCE,HINSTANCE,PWSTR,int) {
 wchar_t a[32768],b[32768],c[32768];
 if(!GetEnvironmentVariableW(L"NIMBUS_DATA_ROOT",a,32768)||
    !GetEnvironmentVariableW(L"NIMBUS_BOOTSTRAP_ROOT",b,32768)||
    !GetCurrentDirectoryW(32768,c)||wcscmp(a,b)||wcscmp(a,c)) return 11;
 HANDLE f=CreateFileW(L"native-launcher-smoke.ok",GENERIC_WRITE,0,nullptr,
                     CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr);
 if(f==INVALID_HANDLE_VALUE) return 12;
 CloseHandle(f); return 0;
}
""", encoding='utf-8')
            for input_path, output, object_name in ((source, root / 'Nimbus.exe', 'bootstrap.obj'),
                    (runtime_source, selected_runtime(root) / executable_name(), 'fixture.obj')):
                subprocess.run(['cl', '/nologo', '/EHsc', '/std:c++17', '/MT', str(input_path),
                                '/Fo:' + str(parent / object_name), '/Fe:' + str(output),
                                '/link', '/SUBSYSTEM:WINDOWS', 'user32.lib'],
                               cwd=parent, check=True, capture_output=True)
            result = subprocess.run([str(root / 'Nimbus.exe')], timeout=15)
            self.assertEqual(result.returncode, 0)
            self.assertTrue((root / 'native-launcher-smoke.ok').is_file())

    @unittest.skipUnless(sys.platform == 'linux' and shutil.which('g++'), 'Linux compiler test')
    def test_native_launcher_selects_runtime_and_passes_shared_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, _ = self.fixture(Path(temporary))
            launcher = root / 'Nimbus'
            source = Path(__file__).resolve().parents[1] / 'native' / 'bootstrap.cpp'
            subprocess.run(['g++', '-std=c++17', '-O2', str(source), '-o', str(launcher)], check=True)
            executable = selected_runtime(root) / executable_name()
            executable.write_text('#!/bin/sh\ntest "$NIMBUS_DATA_ROOT" = "$NIMBUS_BOOTSTRAP_ROOT" || exit 9\ntest "$1" = "argument with spaces" || exit 10\nprintf "%s\\n%s\\n" "$NIMBUS_DATA_ROOT" "$$"\n')
            executable.chmod(0o755)
            with subprocess.Popen([str(launcher), "argument with spaces"], stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True) as app:
                stdout, stderr = app.communicate(timeout=10)
                self.assertEqual(app.returncode, 0, stderr)
                self.assertEqual(stdout.splitlines(), [str(root), str(app.pid)])
            (root / POINTER).write_text('../escape')
            self.assertEqual(subprocess.run([str(launcher)], timeout=10).returncode, 104)
