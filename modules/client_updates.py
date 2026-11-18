"""Public-client updates. No credentials, private service or in-place replacement."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import sys
import tempfile
import threading
import urllib.request
import zipfile

REPOSITORY = "muted-team/nimbus"
RELEASES = "https://github.com/" + REPOSITORY + "/releases"
API = "https://api.github.com/repos/" + REPOSITORY + "/releases/latest"
MAX_ARCHIVE = 2 * 1024 ** 3
MAX_EXPANDED = 6 * 1024 ** 3
# Kept beside the executable by the portable client, including legacy stores.
RESERVED_USER_DATA = ("config.json", "accounts.json", "banned.json", "data.db", "data.db-wal",
        "data.db-shm", "tiktok_cookies.json", "tiktok_cookies.firefox155.json",
        "sessions", "media", "assets", "browser_states", "proxies.txt",
        "registration", "profile-edits", "logs")


class UpdateError(Exception):
    pass


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r"v?\d+\.\d+\.\d+", value):
        raise UpdateError("Некорректная версия релиза GitHub")
    return tuple(map(int, value.removeprefix("v").split(".")))


def target(system=None, machine=None):
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    if machine in ("amd64", "x86_64"):
        return {"Linux": "linux-x86_64", "Windows": "win32-AMD64", "Darwin": "darwin-x86_64"}.get(system)
    if system == "Darwin" and machine in ("aarch64", "arm64"):
        return "darwin-arm64"
    return None


def fetch_json(url):
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "Nimbus-client-updater"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read(2 * 1024 * 1024))


def select_release(payload, current, package_target):
    tag = payload.get("tag_name")
    latest = version(tag)
    if payload.get("draft") or payload.get("prerelease") or not payload.get("published_at"):
        raise UpdateError("GitHub не вернул опубликованный стабильный релиз")
    name = f"nimbus-{tag.removeprefix('v')}-{package_target}.zip"
    asset = next((a for a in payload.get("assets", []) if a.get("name") == name), None)
    digest = (asset or {}).get("digest", "")
    trusted = bool(re.fullmatch(r"sha256:[0-9a-f]{64}", digest or ""))
    expected_url = f"{RELEASES}/download/{tag}/{name}"
    if asset and asset.get("browser_download_url") != expected_url:
        raise UpdateError("Некорректный адрес файла релиза")
    return {"current_version": current, "latest_version": tag.removeprefix("v"),
            "available": latest > version(current), "release_url": RELEASES + "/tag/" + tag,
            "notes": str(payload.get("body") or "")[:12000], "asset": asset,
            "verified": trusted}


def extract_archive(archive, destination, root_name):
    """Validate the complete ZIP before creating any file; never follow links."""
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        if len(members) > 40000 or sum(m.file_size for m in members) > MAX_EXPANDED:
            raise UpdateError("Архив обновления слишком большой")
        seen = set()
        for member in members:
            path = PurePosixPath(member.filename)
            mode = member.external_attr >> 16
            if (member.orig_filename != member.filename or not path.parts
                    or path.parts[0] != root_name or ".." in path.parts
                    or path.is_absolute() or "\\" in member.filename or ":" in member.filename
                    or stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR))
                    or (len(path.parts) > 1 and path.parts[1].casefold() in {n.casefold() for n in RESERVED_USER_DATA})
                    or (len(path.parts) > 3 and path.parts[1] == "runtimes"
                        and path.parts[3].casefold() in {n.casefold() for n in RESERVED_USER_DATA})
                    or any(part.endswith((".", " ")) or any(ord(c) < 32 for c in part)
                           or part.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10))}
                           for part in path.parts)
                    or member.filename.casefold() in seen):
                raise UpdateError("Небезопасный архив обновления")
            seen.add(member.filename.casefold())
        for member in members:
            path = destination.joinpath(*PurePosixPath(member.filename).parts)
            if member.is_dir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as source, path.open("xb") as output:
                    shutil.copyfileobj(source, output)
                path.chmod(0o755 if (member.external_attr >> 16) & 0o111 else 0o644)


def runtime_inventory(directory):
    from . import bootstrap
    bootstrap._plain(directory, directory=True)
    files = {}
    for path in directory.rglob("*"):
        bootstrap._plain(path, directory=path.is_dir())
        if path.is_file():
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            files[path.relative_to(directory).as_posix()] = digest.hexdigest()
    return files


class Updater:
    def __init__(self, app_dir, current, packaged=False, package_target=None, guarded=False, executable=None):
        self.app_dir = Path(app_dir).resolve()
        self.current = current
        self.packaged = packaged
        self.guarded = guarded
        self.executable = Path(executable or sys.executable).absolute()
        self.target = target() if package_target is None else package_target
        self.lock = threading.Lock()
        self.release = None
        self.staged = None
        self._staged_inventory = None

    def _exclusive(self):
        if not self.lock.acquire(blocking=False):
            raise UpdateError("Обновление уже выполняется")

    def _guarded_installation(self):
        if not (self.packaged and self.guarded and self.target in ("linux-x86_64", "win32-AMD64")):
            return False
        from . import bootstrap
        try:
            runtime = bootstrap.selected_runtime(self.app_dir)
            return (runtime.name == "runtime-v" + self.current
                    and self.executable == runtime / bootstrap.executable_name()
                    and (self.app_dir / bootstrap.launcher_name()).is_file())
        except (bootstrap.BootstrapError, OSError, ValueError):
            return False

    def status(self):
        release = self.release or {"current_version": self.current, "available": False, "release_url": RELEASES}
        supported = self._guarded_installation() and bool(release.get("verified")) and bool(release.get("asset"))
        reason = ("" if supported else "Для этой установки доступно ручное обновление из GitHub Releases.")
        return {k: v for k, v in dict(release, supported=supported, reason=reason,
                                    state="ready" if self.staged else "idle",
                                    can_restart=bool(self.staged and supported)).items()
                if k not in ("asset", "verified")}

    def activation_digest(self):
        """Pin helper verification to the original GitHub-verified snapshot.

        Never derive the expected digest from current staged files: a change
        after preparation must remain detectable by the detached helper.
        """
        if not self.staged or not self._staged_inventory:
            raise UpdateError("Сначала скачайте и проверьте обновление")
        canonical = json.dumps(self._staged_inventory, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def activation_arguments(self):
        """Arguments for the CURRENT runtime helper; never execute staged code.

        The Api must start its own current executable with --activate-runtime,
        then close the window. The helper waits for the process-lifetime guard.
        """
        if not self.staged or not self.status()["can_restart"]:
            raise UpdateError("Перезапуск для этой установки недоступен")
        from . import bootstrap
        _, staged_runtime, root = self.staged
        try:
            marker = bootstrap._marker(staged_runtime / bootstrap.RUNTIME_MARKER)
            if marker.get("version") != self.release["latest_version"]:
                raise bootstrap.BootstrapError("Staged version changed")
            bootstrap._plain(staged_runtime / bootstrap.executable_name())
            if runtime_inventory(staged_runtime) != self._staged_inventory:
                raise bootstrap.BootstrapError("Verified stage changed")
        except (bootstrap.BootstrapError, OSError, ValueError):
            raise UpdateError("Подготовленное обновление повреждено. Скачайте пакет заново.") from None
        return str(root), str(staged_runtime), self.release["latest_version"]

    def check(self):
        self._exclusive()
        try:
            if self.staged:
                return self.status()
            self.release = select_release(fetch_json(API), self.current, self.target)
            return self.status()
        except UpdateError:
            raise
        except Exception:
            raise UpdateError("Не удалось проверить обновления. Проверьте соединение и повторите позже.") from None
        finally:
            self.lock.release()

    def prepare(self):
        self._exclusive()
        scratch = None
        try:
            if self.staged:
                return self.status()
            # Re-read published release, never accept URLs or versions from the UI.
            self.release = select_release(fetch_json(API), self.current, self.target)
            if not self.status()["supported"] or not self.release["available"]:
                raise UpdateError("Совместимое проверенное обновление недоступно")
            root_name = "Nimbus v" + self.release["latest_version"]
            scratch = Path(tempfile.mkdtemp(prefix=".nimbus-update-", dir=self.app_dir))
            asset = self.release["asset"]
            digest = hashlib.sha256()
            archive = scratch / "package.zip"
            request = urllib.request.Request(asset["browser_download_url"], headers={"User-Agent": "Nimbus-client-updater"})
            total = 0
            with urllib.request.urlopen(request, timeout=60) as response, archive.open("xb") as output:
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_ARCHIVE or total > asset.get("size", 0):
                        raise UpdateError("Неверный размер обновления")
                    output.write(chunk)
                    digest.update(chunk)
            if total != asset.get("size") or "sha256:" + digest.hexdigest() != asset["digest"]:
                raise UpdateError("Проверка целостности обновления не пройдена")
            from . import bootstrap
            extract_archive(archive, scratch, root_name)
            unpacked = scratch / root_name
            runtime = bootstrap.selected_runtime(unpacked)
            expected_runtime = "runtime-v" + self.release["latest_version"]
            if runtime.name != expected_runtime:
                raise UpdateError("Версия пакета не совпадает с релизом")
            # Protocol 1 upgrades code only: the downloaded launcher is never
            # installed over the immutable launcher of the current installation.
            allowed = {bootstrap.launcher_name(), bootstrap.MARKER, bootstrap.POINTER, "runtimes"}
            if ({p.name for p in unpacked.iterdir()} != allowed
                    or {p.name for p in (unpacked / "runtimes").iterdir()} != {expected_runtime}
                    or not (runtime / "ui" / "index.html").is_file()):
                raise UpdateError("Неполный или несовместимый пакет обновления")
            bootstrap._plain(unpacked / bootstrap.launcher_name())
            executable = runtime / bootstrap.executable_name()
            if not self.target.startswith("win32"):
                executable.chmod(0o755)
            self._staged_inventory = runtime_inventory(runtime)
            self.staged = (scratch, runtime, self.app_dir)
            scratch = None
            return self.status()
        except UpdateError:
            raise
        except Exception:
            raise UpdateError("Не удалось подготовить обновление. Текущая версия и данные сохранены.") from None
        finally:
            if scratch:
                shutil.rmtree(scratch, ignore_errors=True)
            self.lock.release()
