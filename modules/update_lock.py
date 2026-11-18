"""Process lifetime guard for portable-client update handoff.

All cooperating versions in one parent directory use the same file. Never unlink
it: replacing the inode would allow two independent locks. This guard does not
claim to protect against older executables which predate the guard.
"""
import os
from pathlib import Path
import sys
import time


class InstallationBusy(RuntimeError):
    pass


class InstallationLock:
    def __init__(self, directory):
        self.path = Path(directory).resolve() / '.nimbus-installation.lock'
        self._file = None

    def acquire(self, timeout=0):
        if self._file is not None:
            raise RuntimeError('Installation lock already acquired')
        if sys.platform not in ('linux', 'win32'):
            raise RuntimeError('Automatic updates support Linux and Windows only')
        if self.path.is_symlink():
            raise RuntimeError('Installation lock must not be a symbolic link')
        if os.name == 'nt' and self.path.exists():
            import stat
            if getattr(self.path.stat(follow_symlinks=False), 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise RuntimeError('Installation lock must not be a reparse point')
        descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        handle = os.fdopen(descriptor, 'r+b')
        os.set_inheritable(handle.fileno(), False)
        # Windows byte-range locking needs a real byte and identical offsets.
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b'\0')
            handle.flush()
        deadline = time.monotonic() + timeout
        try:
            while True:
                handle.seek(0)
                try:
                    if sys.platform == 'win32':
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self._file = handle
                    return self
                except OSError as error:
                    import errno
                    if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                        raise
                    if time.monotonic() >= deadline:
                        raise InstallationBusy('Another Nimbus process owns this installation') from error
                    time.sleep(min(.1, max(0, deadline - time.monotonic())))
        except BaseException:
            handle.close()
            raise

    def close(self):
        if self._file is not None:
            # Both operating systems release locks when the owning process dies.
            self._file.close()
            self._file = None
