"""Synthetic process tests; no user app, GUI or network access."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from modules.update_lock import InstallationBusy, InstallationLock

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform in ('linux', 'win32'), 'supported platforms')
class InstallationLockTests(unittest.TestCase):
    def test_separate_process_cannot_acquire_until_owner_exits(self):
        with tempfile.TemporaryDirectory() as directory:
            code = ('from modules.update_lock import InstallationLock; import sys; '
                    'guard=InstallationLock(sys.argv[1]).acquire(); '
                    'print("locked",flush=True); sys.stdin.readline()')
            owner = subprocess.Popen([sys.executable, '-c', code, directory], cwd=ROOT,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     text=True)
            try:
                self.assertEqual(owner.stdout.readline().strip(), 'locked')
                with self.assertRaises(InstallationBusy):
                    InstallationLock(directory).acquire()
                owner.stdin.write('\n')
                owner.stdin.flush()
                self.assertEqual(owner.wait(timeout=5), 0)
                lock = InstallationLock(directory).acquire()
                lock.close()
                self.assertTrue((Path(directory) / '.nimbus-installation.lock').exists())
            finally:
                if owner.poll() is None:
                    owner.kill()
                    owner.wait()
                owner.stdin.close()
                owner.stdout.close()

    def test_lock_symlink_does_not_modify_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'private-fixture'
            target.write_bytes(b'')
            try:
                (root / '.nimbus-installation.lock').symlink_to(target)
            except OSError:
                self.skipTest('Creating symlinks requires platform privileges')
            with self.assertRaises(RuntimeError):
                InstallationLock(directory).acquire()
            self.assertEqual(target.read_bytes(), b'')

    def test_closed_guard_can_be_reacquired(self):
        with tempfile.TemporaryDirectory() as directory:
            guard = InstallationLock(directory).acquire()
            guard.close()
            guard.acquire().close()
