"""Immutable-launcher lifecycle and atomic runtime selection.

The running runtime must own its own OS lock; the launcher never owns it.
Runtime directories are immutable and older directories are not deleted here.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from .update_lock import InstallationLock

POINTER = '.nimbus-current'
MARKER = '.nimbus-bootstrap.json'
RUNTIME_MARKER = '.nimbus-runtime.json'
NAME = re.compile(r'runtime-v[0-9]+\.[0-9]+\.[0-9]+\Z')


class BootstrapError(RuntimeError):
    pass


def _plain(path, directory=False):
    path = Path(path)
    # Windows junctions/reparse points must not redirect managed paths either.
    if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
        raise BootstrapError('Bootstrap paths must not use links or junctions')
    if os.name == 'nt' and path.exists():
        import stat
        if getattr(path.stat(follow_symlinks=False), 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise BootstrapError('Bootstrap paths must not use reparse points')
    if not (path.is_dir() if directory else path.is_file()):
        raise BootstrapError('Bootstrap installation is incomplete')
    return path


def _marker(path):
    _plain(path)
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise BootstrapError('Invalid bootstrap marker') from error
    if (not isinstance(payload, dict) or type(payload.get('format')) is not int
            or payload.get('format') != 1):
        raise BootstrapError('Unsupported bootstrap protocol')
    return payload


def root_directory(path):
    root = Path(path).absolute()
    _plain(root, directory=True)
    _marker(root / MARKER)
    _plain(root / 'runtimes', directory=True)
    return root


def selected_runtime(root):
    root = root_directory(root)
    pointer = _plain(root / POINTER)
    with pointer.open('rb') as stream:
        value = stream.read(81)
    if len(value) > 80:
        raise BootstrapError('Invalid runtime pointer')
    try:
        name = value.decode('ascii').removesuffix('\n')
    except UnicodeError as error:
        raise BootstrapError('Invalid runtime pointer') from error
    if not NAME.fullmatch(name):
        raise BootstrapError('Invalid runtime pointer')
    runtime = _plain(root / 'runtimes' / name, directory=True)
    marker = _marker(runtime / RUNTIME_MARKER)
    if marker.get('version') != name.removeprefix('runtime-v'):
        raise BootstrapError('Runtime version does not match pointer')
    _plain(runtime / executable_name())
    return runtime


def executable_name():
    return 'Nimbus-runtime.exe' if sys.platform == 'win32' else 'Nimbus-runtime'


def launcher_name():
    return 'Nimbus.exe' if sys.platform == 'win32' else 'Nimbus'


def enter_runtime(executable, environ=None):
    """Call before importing application modules or creating any user files.

    Keep the returned guard referenced until process exit, including all threads.
    Direct runtime starts and stale launcher selections are rejected.
    """
    environ = os.environ if environ is None else environ
    claimed = environ.get('NIMBUS_BOOTSTRAP_ROOT')
    if not claimed or environ.get('NIMBUS_DATA_ROOT') != claimed:
        raise BootstrapError('Start Nimbus using its top-level launcher')
    root = root_directory(claimed)
    guard = InstallationLock(root).acquire()
    try:
        runtime = selected_runtime(root)
        actual = Path(executable).absolute()
        _plain(actual)
        if actual != runtime / executable_name():
            raise BootstrapError('The launcher selected a stale or different runtime')
        return guard
    except BaseException:
        guard.close()
        raise


def _sync_dir(path):
    if os.name != 'nt':
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _durable_move(source, destination, replace=False):
    if os.name == 'nt':
        # MOVEFILE_WRITE_THROUGH waits for filesystem flush; do not use a plain
        # unlink+rename sequence for the live pointer on Windows.
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        move = kernel.MoveFileExW
        move.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
        move.restype = wintypes.BOOL
        flags = 0x8 | (0x1 if replace else 0)  # WRITE_THROUGH | REPLACE_EXISTING
        if not move(str(source), str(destination), flags):
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        if replace:
            os.replace(source, destination)
        else:
            source.rename(destination)
        _sync_dir(source.parent)
        if source.parent != destination.parent:
            _sync_dir(destination.parent)


def inventory_digest(directory):
    """Hash a canonical content inventory; matches the parent's verified snapshot."""
    directory = _plain(directory, directory=True)
    files = {}
    for path in directory.rglob('*'):
        _plain(path, directory=path.is_dir())
        if path.is_file():
            value = hashlib.sha256()
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    value.update(chunk)
            files[path.relative_to(directory).as_posix()] = value.hexdigest()
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def _activation_preflight(root, source, version, expected):
    name = 'runtime-v' + version
    if len(name) > 79 or not NAME.fullmatch(name):
        raise BootstrapError('Invalid release version')
    selected_runtime(root)
    launcher = _plain(root / launcher_name())
    if sys.platform == 'linux' and not os.access(launcher, os.X_OK):
        raise BootstrapError('Stable launcher is not executable')
    _plain(source, directory=True)
    metadata = _marker(source / RUNTIME_MARKER)
    if metadata.get('version') != version:
        raise BootstrapError('Staged runtime version is invalid')
    staged_executable = _plain(source / executable_name())
    if sys.platform == 'linux' and not os.access(staged_executable, os.X_OK):
        raise BootstrapError('Staged runtime is not executable')
    if inventory_digest(source) != expected:
        raise BootstrapError('Staged runtime differs from the verified inventory')
    temporary = root / (POINTER + '.pending')
    if temporary.exists() or temporary.is_symlink():
        _plain(temporary)
        with temporary.open('rb') as stream:
            pending = stream.read(81)
        try:
            pending_name = pending.decode('ascii').removesuffix('\n')
        except UnicodeError as error:
            raise BootstrapError('Invalid pending pointer') from error
        if len(pending) > 80 or not NAME.fullmatch(pending_name):
            raise BootstrapError('Invalid pending pointer; current selection unchanged')
    destination = root / 'runtimes' / name
    existing = destination.exists() or destination.is_symlink()
    if existing and inventory_digest(destination) != expected:
        raise BootstrapError('Target runtime differs from verified download')
    if existing and sys.platform == 'linux' and not os.access(destination / executable_name(), os.X_OK):
        raise BootstrapError('Target runtime is not executable')
    return destination, temporary, existing


def activate(root, staged_runtime, version, timeout=120, checkpoint=lambda _: None,
             ready=lambda: None, expected_digest=None):
    """Helper-only: validate before readiness AND after full process handoff.

    Product callers supply expected_digest from the parent's verified in-memory
    snapshot. The optional default supports independent synthetic transactions.
    No user-data file is opened; earlier installed code is never modified.
    """
    root = root_directory(root)
    source = Path(staged_runtime).absolute()
    expected = inventory_digest(source) if expected_digest is None else expected_digest
    if not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected):
        raise BootstrapError('Invalid verified inventory digest')
    _activation_preflight(root, source, version, expected)
    ready()  # No already-known activation failure may authorize closing the UI.
    guard = InstallationLock(root).acquire(timeout=timeout)
    try:
        destination, temporary, existing = _activation_preflight(root, source, version, expected)
        if temporary.exists():
            temporary.unlink()
            _sync_dir(root)
        for path in source.rglob('*'):
            if path.is_file():
                with path.open('r+b') as stream:
                    os.fsync(stream.fileno())
        for directory in sorted((p for p in source.rglob('*') if p.is_dir()),
                                key=lambda p: len(p.parts), reverse=True):
            _sync_dir(directory)
        _sync_dir(source)
        checkpoint('validated')
        # Recheck the parent's content identity at the publication boundary.
        if inventory_digest(source) != expected:
            raise BootstrapError('Staged runtime changed before publication')
        if not existing:
            _durable_move(source, destination)
        checkpoint('runtime-visible')
        if inventory_digest(destination) != expected:
            raise BootstrapError('Published runtime differs from verified download')
        with temporary.open('xb') as stream:
            stream.write((destination.name + '\n').encode('ascii'))
            stream.flush()
            os.fsync(stream.fileno())
        checkpoint('pointer-ready')
        # Detect alterations between publishing code and selecting it.
        if inventory_digest(destination) != expected:
            raise BootstrapError('Published runtime changed before selection')
        if sys.platform == 'linux' and not os.access(destination / executable_name(), os.X_OK):
            raise BootstrapError('Published runtime is not executable')
        _durable_move(temporary, root / POINTER, replace=True)
        checkpoint('activated')
        return destination
    finally:
        guard.close()


def relaunch_current_if_idle(root):
    """Late helper failure: restart intact selection after the old process exited."""
    from .update_lock import InstallationBusy
    root = root_directory(root)
    try:
        guard = InstallationLock(root).acquire()
    except InstallationBusy:
        return False  # Parent or an already-restarted runtime is still alive.
    try:
        selected_runtime(root)
    finally:
        guard.close()
    launch(root)
    return True


def launch(root):
    root = root_directory(root)
    launcher = _plain(root / launcher_name())
    return subprocess.Popen([str(launcher)], cwd=root, close_fds=True)


def cleanup_staging(root, original_source, version):
    """Remove only this updater's private scratch package after successful selection."""
    root = root_directory(root)
    source = Path(original_source).absolute()
    if len(source.parents) < 3:
        return False
    scratch = source.parents[2]
    if (scratch.parent != root or not scratch.name.startswith('.nimbus-update-')
            or source.parent.name != 'runtimes'
            or source.parent.parent.name != 'Nimbus v' + version
            or source.name != 'runtime-v' + version
            or selected_runtime(root).name != source.name):
        return False
    _plain(scratch, directory=True)
    if {p.name for p in scratch.iterdir()} != {'package.zip', 'Nimbus v' + version}:
        return False
    for path in scratch.rglob('*'):
        _plain(path, directory=path.is_dir())
    shutil.rmtree(scratch)
    _sync_dir(root)
    return True
