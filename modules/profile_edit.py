"""Own-profile UI bridge; never performs login, mutation retries or alias renames."""

import contextlib
import hashlib
import json
import os
from pathlib import Path
import threading
from . import accounts, cloud, paths, profiles, proxy_pool, remote

_ROOT = Path(__file__).resolve().parents[1] / "profile-edits"
_lock = threading.RLock()


def _file(username):
    folder = paths.here(_ROOT)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if folder.is_symlink() or (
        os.name != "nt"
        and (folder.stat().st_uid != os.getuid() or folder.stat().st_mode & 0o077)
    ):
        raise ValueError("Небезопасная папка результатов профиля")
    return folder / (hashlib.sha256(username.encode()).hexdigest() + ".json")


def _owner():
    return hashlib.sha256((remote.base() + "\0" + remote.key()).encode()).hexdigest()


def _read(username):
    file = _file(username)
    if not file.exists():
        return None
    row = json.loads(file.read_text(encoding="utf-8"))
    return row if row.get("owner") == _owner() else None


def _save(username, row):
    file = _file(username)
    temporary = file.with_suffix(".tmp")
    fd = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    if os.name != "nt":
        os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(dict(row, owner=_owner()), stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(file)


@contextlib.contextmanager
def _proxy(username):
    if (not isinstance(username, str)
            or not profiles._USERNAME_RE.fullmatch(username) and not accounts.is_email_login(username)):
        raise ValueError("Выберите аккаунт")
    account = accounts.load_account(username)
    retained = account.get("registration_proxy")
    if isinstance(retained, str) and retained:
        yield retained
    else:
        held = proxy_pool.lease(task="login")
        try:
            if not held.url:
                raise ValueError("Для профиля нужен рабочий прокси")
            yield held.url
        finally:
            held.release()


def info(username):
    with _lock, _proxy(username) as proxy:
        result = cloud.profile_info(username, proxy)
        before = result.get("before")
        if (
            result.get("verdict") != "observed"
            or result.get("state_saved") is False
            or result.get("stop_account") is True
            or not isinstance(before, dict)
            or not all(
                isinstance(before.get(field), str)
                for field in ("nickname", "unique_id")
            )
            or not isinstance(before.get("user_id"), str)
            or not profiles._UID_RE.fullmatch(before["user_id"])
            or not profiles._USERNAME_RE.fullmatch(before["unique_id"])
        ):
            raise ValueError("Сервер не подтвердил владельца профиля")
        try:
            profiles.save_identity(username, before)
        except profiles.ProfileError as exc:
            raise ValueError(str(exc)) from None
        except (profiles.sqlite3.Error, OSError):
            result = dict(result, profile_saved=False)
        previous = _read(username)
        if previous:
            if previous.get("expected_uid") == str(before["user_id"]):
                previous["reconciled"] = True
                _save(username, previous)
                result = dict(
                    result,
                    last_result=previous.get("result"),
                    last_requested=previous.get("requested", {}),
                    last_expected_uid=previous.get("expected_uid"),
                )
        return result


def plan(username, changes):
    with _lock, _proxy(username) as proxy:
        return cloud.profile_plan(username, proxy, changes)


def _uncertain(result):
    return (
        result.get("verdict") == "unknown"
        or result.get("state_saved") is False
        or any(
            isinstance(step, dict) and step.get("verdict") == "unknown"
            for step in (
                result.get("steps") if isinstance(result.get("steps"), list) else []
            )
        )
    )


def _requires_readback(row):
    result = row.get("result", {})
    if _uncertain(result) or result.get("stop_account") is True:
        return True
    verdict = result.get("verdict")
    if verdict in ("blocked", "rejected"):
        return False
    requested, uid = row.get("requested", {}), row.get("expected_uid")
    before = result.get("before") if isinstance(result.get("before"), dict) else {}
    after = result.get("after") if isinstance(result.get("after"), dict) else {}
    if verdict == "noop":
        return before.get("user_id") != uid or any(
            field == "avatar_data" or before.get(field) != value
            for field, value in requested.items()
        )
    if (
        verdict not in ("confirmed", "partial")
        or before.get("user_id") != uid
        or after.get("user_id") != uid
    ):
        return True
    if not all(
        isinstance(after.get(field), str) for field in ("nickname", "unique_id")
    ):
        return True
    confirmed = result.get("confirmed_fields")
    if not isinstance(confirmed, list):
        return True
    fields = [field for field in requested if field in confirmed]
    if verdict == "confirmed" and (
        result.get("platform_verified") is not True or len(fields) != len(requested)
    ):
        return True
    if not fields:
        return True
    return any(
        not after.get("avatar_uri")
        if field == "avatar_data"
        else after.get(field) != requested[field]
        for field in fields
    )


def update(username, changes, expected_uid, acknowledge=False):
    if not isinstance(changes, dict) or set(changes) - {
        "nickname",
        "unique_id",
        "avatar_data",
    }:
        raise ValueError("Неизвестные поля профиля")
    if not isinstance(expected_uid, str) or not profiles._UID_RE.fullmatch(expected_uid):
        raise ValueError("Сначала прочитайте профиль")
    if type(acknowledge) is not bool:
        raise ValueError("Подтвердите ограничения смены имени")
    with _lock, _proxy(username) as proxy:
        previous = _read(username)
        if previous and not previous.get("reconciled") and _requires_readback(previous):
            raise ValueError(
                "Сначала перечитайте профиль: результат предыдущего изменения не подтверждён"
            )
        # Server plan is strictly offline and provides canonical username rules.
        prepared = cloud.profile_plan(username, proxy, changes)
        if (
            prepared.get("verdict") != "planned"
            or prepared.get("network_performed") is not False
        ):
            raise ValueError("Сервер не подтвердил проверку полей")
        requested = prepared.get("requested")
        if not isinstance(requested, dict):
            raise ValueError("Сервер не подтвердил формат полей")
        canonical = {
            **changes,
            **{k: v for k, v in requested.items() if k != "avatar_data"},
        }
        row = {
            "expected_uid": expected_uid,
            "requested": {
                k: ("retained-avatar" if k == "avatar_data" else v)
                for k, v in canonical.items()
            },
            "reconciled": False,
            "result": {
                "verdict": "unknown",
                "confirmed_fields": [],
                "message": "Результат изменения неизвестен. Перечитайте профиль перед повтором",
            },
        }
        _save(username, row)  # Persist before the single protected mutation call.
        try:
            result = cloud.profile_update(
                username, proxy, canonical, expected_uid, acknowledge
            )
        except remote.RemoteError as exc:
            if not exc.outcome_unknown and exc.status in (
                400,
                401,
                402,
                403,
                404,
                422,
                429,
            ):
                result = {
                    "verdict": "rejected",
                    "confirmed_fields": [],
                    "message": str(exc),
                }
            else:
                result = row["result"]
        row["result"] = result
        if result.get("verdict") in ("confirmed", "partial", "noop") and not _requires_readback(row):
            identity = result.get("before") if result["verdict"] == "noop" else result.get("after")
            try:
                profiles.save_identity(username, identity)
            except (profiles.ProfileError, OSError, profiles.sqlite3.Error):
                result = row["result"] = dict(result, profile_saved=False)
        _save(username, row)
        return result
