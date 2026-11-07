"""Local cookie import and encrypted service state persistence."""

import json
import math
import re
import secrets
import threading
import time
from http.cookiejar import Cookie, LWPCookieJar
from pathlib import Path

from . import client_device, config, paths


_ROOT = Path(__file__).resolve().parent.parent
SESSIONS_DIR = _ROOT / "sessions"
COOKIES_FILE = _ROOT / "tiktok_cookies.json"
LEGACY_COOKIES_FILE = _ROOT / "tiktok_cookies.jar"
SESSION_SUFFIX = ".json"
LEGACY_SESSION_SUFFIX = ".jar"
STATE_SUFFIX = ".state"
DEVICE_STATE_SUFFIX = ".device.state"
DEVICE_SUFFIX = ".device.json"
COOKIE_SCHEMA = "tiktok-web-api.cookies"
COOKIE_SCHEMA_VERSION = 1

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_files_lock = threading.RLock()
_state_generations = {}


def normalize_cookie_import(text: str) -> str:
    """Browser JSON or a program jar -> validated, domain-preserving session JSON."""
    if not isinstance(text, str) or len(text.encode('utf-8')) > 1024 * 1024:
        raise ValueError('JSON с куки слишком большой')
    try:
        raw = json.loads(text)
    except ValueError:
        raise ValueError('Не удалось прочитать JSON с куки') from None
    if isinstance(raw, dict):
        if raw.get('schema') not in (None, COOKIE_SCHEMA) or raw.get('version', 1) != 1:
            raise ValueError('Неизвестный формат куки')
        raw = raw.get('cookies')
    if not isinstance(raw, list) or not 1 <= len(raw) <= 500:
        raise ValueError('Укажите JSON-массив с куки TikTok')
    normalized = []
    authenticated = False
    for row in raw:
        if not isinstance(row, dict):
            raise ValueError('Неверная запись куки')
        name, value = row.get('name'), row.get('value')
        domain = row.get('domain', '.tiktok.com')
        path = row.get('path', '/')
        if (not isinstance(name, str) or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name)
                or not isinstance(value, str) or any(ord(c) < 32 or ord(c) == 127 or c == ';' for c in value)
                or not isinstance(domain, str) or not isinstance(path, str)
                or not path.startswith('/') or any(ord(c) < 32 or ord(c) == 127 for c in path)):
            raise ValueError('Неверное имя, значение или путь куки')
        host = domain.lstrip('.').lower()
        if host != 'tiktok.com' and not re.fullmatch(r'[a-z0-9.-]+\.tiktok\.com', host):
            raise ValueError('Разрешены только куки TikTok')
        expiry = row.get('expires', row.get('expirationDate', row.get('expiration')))
        if expiry is not None and expiry != -1:
            if (type(expiry) not in (int, float) or not math.isfinite(expiry) or expiry < 0):
                raise ValueError('Неверный срок действия куки')
            expiry = int(expiry)
        else:
            expiry = None
        active = expiry is None or expiry > time.time()
        if name in ('sid_guard', 'sessionid', 'sid_tt') and value and active:
            authenticated = True
        normalized.append({'name': name, 'value': value, 'domain': domain.lower(),
                           'path': path, 'secure': bool(row.get('secure')),
                           'httpOnly': bool(row.get('httpOnly')), 'expires': expiry,
                           # Imported tab cookies must survive the first server request.
                           'discard': False, 'domain_specified': True,
                           'domain_initial_dot': domain.startswith('.')})
    if not authenticated:
        raise ValueError('Нет действующей куки авторизации TikTok')
    return json.dumps({'schema': COOKIE_SCHEMA, 'version': COOKIE_SCHEMA_VERSION,
                       'cookies': normalized}, ensure_ascii=False)


def state_generation(path: Path) -> int:
    """Capture a concrete state's generation before a remote operation."""
    with _files_lock:
        return _state_generations.get(Path(path), 0)


def write_state_if_current(path: Path, token: str, generation: int) -> bool:
    """Do not restore state cleared or renamed while its response was pending."""
    path = Path(path)
    with _files_lock:
        if _state_generations.get(path, 0) != generation:
            return False
        config.write_text_atomic(path, token)
        return True


def commit_cookie_import(path: Path, token: str, generation: int, previous,
                         save_account, device_update=None) -> None:
    """Commit the registry with its verified state, rejecting changed local state."""
    path = Path(path)
    with _files_lock:
        current = path.read_bytes() if path.exists() else None
        if _state_generations.get(path, 0) != generation or current != previous:
            raise ValueError('Состояние аккаунта изменилось во время проверки куки')
        device_path, device_previous, device_text = device_update or (None, None, None)
        if device_path is not None:
            current_device = device_path.read_bytes() if device_path.exists() else None
            if current_device != device_previous:
                raise ValueError('Параметры аккаунта изменились во время проверки куки')
        config.write_text_atomic(path, token)
        try:
            if device_path is not None:
                config.write_text_atomic(device_path, device_text)
            save_account()
        except Exception:
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                config.write_text_atomic(path, previous.decode('utf-8'))
            if device_path is not None:
                if device_previous is None:
                    device_path.unlink(missing_ok=True)
                else:
                    config.write_text_atomic(device_path, device_previous.decode('utf-8'))
            raise
        _state_generations[path] = generation + 1


def cookie_import_snapshot() -> dict:
    """Capture before owner discovery so an intervening clear cannot revive state."""
    with _files_lock:
        generations = dict(_state_generations)
        folder = session_directory()
        candidates = set(generations)
        if folder.exists():
            candidates.update(folder.glob('*.state'))
            candidates.update(folder.glob('*.device.json'))
        return {path: (generations.get(path, 0), path.read_bytes() if path.exists() else None)
                for path in candidates}


def complete_login_if_current(auth_path: Path, token: str, auth_generation: int,
                              kept_path: Path, kept_generation: int) -> bool:
    """Save login and consume its kept device without a concurrent local clear."""
    auth_path, kept_path = Path(auth_path), Path(kept_path)
    with _files_lock:
        if (_state_generations.get(auth_path, 0) != auth_generation
                or _state_generations.get(kept_path, 0) != kept_generation):
            return False
        config.write_text_atomic(auth_path, token)
        kept_path.unlink(missing_ok=True)
        return True


def remove_states_if_current(path_generations) -> bool:
    """Do not remove state replaced by clear or rename during a remote reply."""
    targets = [(Path(path), generation) for path, generation in path_generations]
    with _files_lock:
        if any(_state_generations.get(path, 0) != generation for path, generation in targets):
            return False
        for path, _generation in targets:
            path.unlink(missing_ok=True)
        return True


def _invalidate_state_paths(paths_to_invalidate) -> None:
    for path in paths_to_invalidate:
        _state_generations[path] = _state_generations.get(path, 0) + 1


def _safe_filename(username: str) -> str:
    return _SAFE_NAME_RE.sub("_", username) or "_"


def _session_paths(username: str = None):
    if not username:
        if client_device.IS_FIREFOX:
            return (paths.here(COOKIES_FILE).with_name("tiktok_cookies.firefox155.json"),
                    paths.here(LEGACY_COOKIES_FILE).with_name("tiktok_cookies.firefox155.jar"))
        return paths.here(COOKIES_FILE), paths.here(LEGACY_COOKIES_FILE)
    directory = session_directory()
    directory.mkdir(parents=True, exist_ok=True)
    stem = _safe_filename(username)
    return (directory / f"{stem}{SESSION_SUFFIX}",
            directory / f"{stem}{LEGACY_SESSION_SUFFIX}")


def _cookie_to_dict(cookie: Cookie) -> dict:
    rest = dict(getattr(cookie, "_rest", {}) or {})
    http_only = any(str(key).lower() == "httponly" for key in rest)
    return {
        "version": cookie.version, "name": cookie.name, "value": cookie.value,
        "port": cookie.port, "port_specified": cookie.port_specified,
        "domain": cookie.domain, "domain_specified": cookie.domain_specified,
        "domain_initial_dot": cookie.domain_initial_dot, "path": cookie.path,
        "path_specified": cookie.path_specified, "secure": cookie.secure,
        "expires": cookie.expires, "discard": cookie.discard,
        "comment": cookie.comment, "comment_url": cookie.comment_url,
        "rest": rest, "httpOnly": http_only, "rfc2109": cookie.rfc2109,
    }


def _write_cookie_json(path: Path, cookies) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema": COOKIE_SCHEMA, "version": COOKIE_SCHEMA_VERSION,
               "cookies": [_cookie_to_dict(cookie) for cookie in cookies]}
    config.write_text_atomic(
        path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _migrate_legacy(current: Path, legacy: Path) -> None:
    if current.exists() or not legacy.exists():
        return
    jar = LWPCookieJar(str(legacy))
    jar.load(ignore_discard=True, ignore_expires=True)
    _write_cookie_json(current, jar)
    legacy.unlink()


def session_file(username: str = None) -> Path:
    """Path to a JSON cookie jar, migrating the old LWP jar when needed."""
    current, legacy = _session_paths(username)
    with _files_lock:
        _migrate_legacy(current, legacy)
    return current


def state_file(username: str) -> Path:
    return session_file(username).with_suffix(STATE_SUFFIX)


def device_state_file(username: str) -> Path:
    return session_file(username).with_suffix(DEVICE_STATE_SUFFIX)


def device_file(username: str) -> Path:
    return session_directory() / f"{_safe_filename(username)}{DEVICE_SUFFIX}"


def sticky_proxy(url: str, username: str, *, device_path=None, lock=None) -> str:
    """Keep a NoShadow account route in its device, without network access.

    Explicit proxy modes stay as supplied. Only a route that the provider
    helper can complete gets a saved session/time; malformed existing device
    data stops the operation rather than silently replacing its identity.
    Server-side callers supply their device path and existing storage lock.
    """
    from . import proxies
    if not username or proxies.noshadow_session(url, "probe") == url:
        return url
    guard = _files_lock if lock is None else lock
    with guard, _files_lock:
        target = device_file(username) if device_path is None else Path(device_path)
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except FileNotFoundError:
            data = {}
        except ValueError as exc:
            raise ValueError("устройство аккаунта повреждено — прокси не изменён") from exc
        if not isinstance(data, dict):
            raise ValueError("устройство аккаунта повреждено — прокси не изменён")
        if "noshadow_sticky" in data:
            record = data["noshadow_sticky"]
            if (not isinstance(record, dict)
                    or not isinstance(record.get("session_id"), str)
                    or not re.fullmatch(r"[A-Za-z0-9]{1,64}", record["session_id"])
                    or type(record.get("minutes")) is not int
                    or not 1 <= record["minutes"] <= 120):
                raise ValueError("сохранённые параметры прокси повреждены")
        else:
            record = {"session_id": secrets.token_hex(8), "minutes": 15}
            target.parent.mkdir(parents=True, exist_ok=True)
            config.write_text_atomic(target, json.dumps(
                {**data, "noshadow_sticky": record}, ensure_ascii=False, indent=1))
        return proxies.noshadow_session(url, record["session_id"], record["minutes"])


def session_directory() -> Path:
    folder = paths.here(SESSIONS_DIR)
    return folder / "firefox155" if client_device.IS_FIREFOX else folder


def has_session(username: str) -> bool:
    """Presence in the active browser namespace; never migrate a legacy jar."""
    current, legacy = _session_paths(username)
    return current.exists() or legacy.exists() or current.with_suffix(STATE_SUFFIX).exists()


def _read_facts(path: Path) -> tuple:
    """(факты, до какого времени они верны) по файлу кук. Куки с вышедшим
    сроком в факты не попадают, поэтому ответ верен лишь до ближайшего срока
    из учтённых кук (inf — сроков нет)."""
    out = {"region": None, "lang": None, "idc": None}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(raw, dict) or raw.get("schema") != COOKIE_SCHEMA
                or raw.get("version") != COOKIE_SCHEMA_VERSION
                or not isinstance(raw.get("cookies"), list)):
            return out, float("inf")
        now = time.time()
        valid_until = float("inf")
        cookies = {}
        for cookie in raw["cookies"]:
            if not isinstance(cookie, dict) or cookie.get("discard"):
                continue
            expires = cookie.get("expires")
            if expires is not None:
                if float(expires) <= now:
                    continue
                valid_until = min(valid_until, float(expires))
            cookies[cookie.get("name")] = cookie.get("value")
    except (OSError, ValueError, TypeError):
        return out, 0.0
    region = cookies.get("store-country-code")
    lang = cookies.get("tiktok_webapp_lang")
    idc = cookies.get("store-idc")
    out["region"] = region.upper() if isinstance(region, str) and region else None
    out["lang"] = lang if isinstance(lang, str) and lang else None
    out["idc"] = idc if isinstance(idc, str) and idc else None
    return out, valid_until


# факты по файлу кук: путь -> (mtime_ns, размер, факты, верны до). Список
# аккаунтов спрашивает их у каждого при каждом опросе, а файл меняется редко.
_facts_cache = {}
_facts_lock = threading.Lock()


def session_facts(username: str = None) -> dict:
    """Return non-secret region/language/data-center facts from saved cookies.

    Читается файл кук заново, только когда он сменился (время изменения или
    размер) либо у учтённой куки вышел срок."""
    path = session_file(username)
    try:
        stat = path.stat()
    except OSError:
        return {"region": None, "lang": None, "idc": None}
    key = (stat.st_mtime_ns, stat.st_size)
    with _facts_lock:
        hit = _facts_cache.get(path)
    if hit and hit[0] == key and time.time() < hit[2]:
        return dict(hit[1])
    facts, valid_until = _read_facts(path)
    with _facts_lock:
        _facts_cache[path] = (key, facts, valid_until)
    return dict(facts)


def _account_files(username: str) -> list:
    """All local account files, without migrating legacy jars or reading state."""
    stem = _safe_filename(username)
    files = []
    for profile in client_device.BROWSER_PROFILES:
        with client_device.use_browser_profile(profile):
            directory = session_directory()
        files.extend(directory / f"{stem}{suffix}" for suffix in (
            SESSION_SUFFIX, LEGACY_SESSION_SUFFIX, STATE_SUFFIX,
            DEVICE_SUFFIX, DEVICE_STATE_SUFFIX))
    return files


def rename_jar(old: str, new: str) -> bool:
    """Rename account data in every browser namespace, including saved devices."""
    if not old or not new or old == new:
        return False
    with _files_lock:
        old_paths, new_paths = _account_files(old), _account_files(new)
        _invalidate_state_paths(old_paths + new_paths)
        moves = []
        for source, target in zip(old_paths, new_paths):
            try:
                source.stat()
            except FileNotFoundError:
                continue
            moves.append((source, target))
        if not moves:
            return False
        moved = []
        try:
            for source, target in moves:
                source.replace(target)
                moved.append((source, target))
            return True
        except OSError as exc:
            for source, target in reversed(moved):
                target.replace(source)
            print(f"[session] не удалось переименовать локальные данные {old} -> {new}: "
                  f"{type(exc).__name__}: {exc}")
            raise


def clear_session(username: str, new_device: bool = False) -> int:
    """Remove authentication in every browser namespace; optionally forget devices."""
    if not isinstance(username, str) or not username.strip():
        raise ValueError("нужен username аккаунта")
    # вкладочный tab.json пишет и стирает только сервер (session_manager): в
    # сборке клиента этого модуля нет, и импорт отсюда ронял «Забыть вход»
    with _files_lock:
        removed = 0
        stem = _safe_filename(username)
        account_paths = _account_files(username)
        # Even an absent file or a preserved device must reject older replies.
        _invalidate_state_paths(account_paths)
        for path in account_paths:
            is_device = path.name in (stem + DEVICE_SUFFIX, stem + DEVICE_STATE_SUFFIX)
            if is_device and not new_device:
                continue
            try:
                path.unlink()
                if not is_device:
                    removed = 1
            except FileNotFoundError:
                pass
    return removed
