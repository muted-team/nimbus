# Portable update lifecycle

Linux and Windows bootstrap packages have one stable `Nimbus` / `Nimbus.exe`
launcher, a `.nimbus-current` pointer, and immutable code directories under
`runtimes/runtime-vVERSION`. The pointer is ASCII with a single LF terminator.
The runtime marker and installation marker use bootstrap protocol `format: 1`.
macOS packages retain the existing manual installation path.

The launcher sets `NIMBUS_DATA_ROOT` and `NIMBUS_BOOTSTRAP_ROOT` to its installation
directory. Before importing the GUI or application modules, the runtime obtains
an OS process lock and checks that the pointer still selects its own executable.
A direct runtime launch or stale launcher selection fails before user files are
created. The runtime retains this lock until the whole process terminates;
closing the HTTP listener alone is insufficient. The launcher does not own this
lock, so terminating the launcher cannot release a still-running runtime's lock.

Before requesting restart, the native bridge freezes GET/PUT/POST API ingress and
drains requests already admitted. New requests receive 503. Proxy maintenance
loops park cooperatively after finishing their current work; they never cancel
manual checks or user tasks. Any remaining application-owned worker or unresolved
registration, browser-job, or profile-edit intent blocks restart without a remote
request. Failure reopens ingress and resumes maintenance. The helper must signal
validated readiness before the window is closed. Known target conflicts and invalid
pending pointers are checked before this readiness signal. The parent passes a
SHA256 of its verified in-memory file inventory to the helper, which rechecks it
before readiness, after the process handoff, and at publication boundaries. No force-stop of a user task is
part of this path.

An activation helper runs from the current, intact runtime, without importing the
GUI or starting data writers. It waits for that same lock, validates the downloaded
runtime, flushes its files, publishes the complete runtime directory, and atomically
replaces the pointer. On Windows, publication and pointer replacement use
`MoveFileExW` with `MOVEFILE_WRITE_THROUGH`; on Linux, files and directories are
flushed around rename. The helper then starts the stable launcher. It never runs
from the directory being moved: Windows may hold that executable open.

A late activation failure relaunches the intact current selection only after an
OS lock check proves the old runtime has exited; a still-live parent is never
replaced with a duplicate process.

A process interruption before pointer replacement leaves the previous runtime
selected. An interruption afterwards leaves the new complete runtime selected.
An identical orphan runtime from a prior interruption can be reused after
comparing the newly verified download. A changed orphan or invalid pending pointer
causes refusal. A newly downloaded archive remains subject to GitHub asset SHA256,
archive validation, and the updater's bootstrap compatibility checks.

Activation never enumerates, copies, moves, or opens user data. Config, accounts,
SQLite databases and their WAL/SHM files, browser sessions, media, registration and
profile-edit records remain in the same data directory. Previous runtime
directories are installed code, not backups of user data. Automatic code cleanup
is deliberately outside this lifecycle.

Legacy flat packages do not provide this guard or shared data-root contract.
They cannot safely participate in automatic activation. Their first transition
requires manual installation. Close all Nimbus instances, unpack the bootstrap
package into a separate directory, and copy the existing user data beside the
top-level `Nimbus` or `Nimbus.exe` before first launch. The
[user guide](../ИНСТРУКЦИЯ.md#data) lists the data files and directories to copy.
Keep the old directory until the new installation has been checked. Bootstrap
mode deliberately skips legacy sibling-data migration.

Offline tests cover pointer validation, symlink refusal, stale/direct runtime
refusal, process locks, interruption and hard process exits, retries, and byte-exact
preservation of a synthetic SQLite database with a live WAL/SHM connection. The
Linux test also compiles and executes the native launcher with a synthetic runtime.
These tests do not prove power-failure behavior on every filesystem. Windows
native compilation/runtime smoke must pass on Windows before claiming Windows
release acceptance; a simulated platform branch is insufficient.
