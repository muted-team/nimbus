"""Explicit real registration jobs; credentials and opaque states stay on disk."""

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import random
import threading
from urllib.parse import urlsplit, urlunsplit
from . import accounts, client_session, cloud, paths, proxies, proxy_pool, remote

_lock = threading.RLock()
_held_leases = {}
_ROOT = Path(__file__).resolve().parents[1] / "registration"
_JOB = re.compile(r"^[a-f0-9]{32}$")


def _directory():
    folder = paths.here(_ROOT)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if folder.is_symlink() or (
        os.name != "nt"
        and (folder.stat().st_uid != os.getuid() or folder.stat().st_mode & 0o077)
    ):
        raise ValueError("Небезопасная папка регистрации")
    return folder


def _write(path, data):
    temporary = path.with_name(path.name + ".tmp")
    fd = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    if os.name != "nt":
        os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    if os.name != "nt":
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


def _owner():
    return hashlib.sha256((remote.base() + "\0" + remote.key()).encode()).hexdigest()


def _load():
    file = _directory() / "current.json"
    if not file.exists():
        return None
    row = json.loads(file.read_text())
    if row.get("owner") != _owner():
        return None
    return row


def _public(row):
    return {
        "scope": row.get("owner"),
        **{
            key: row[key]
            for key in (
                "job_id",
                "mode",
                "status",
                "username",
                "reason",
                "account_saved",
                "billing_status",
                "username_selection",
                "server_reason",
                "email_domain",
            )
            if key in row
        },
    }


def _remember(row):
    _write(_directory() / "current.json", row)
    local_id = row.get("local_id")
    if isinstance(local_id, str) and re.fullmatch(r"[a-f0-9]{32}", local_id):
        _write(_directory() / ("request-" + local_id + ".json"), row)


def history():
    with _lock:
        rows = []
        for path in sorted(
            _directory().glob("request-*.json"),
            key=lambda p: p.stat().st_mtime_ns,
            reverse=True,
        )[:100]:
            row = json.loads(path.read_text())
            if isinstance(row, dict) and row.get("owner") == _owner():
                rows.append(_public(row))
        return {"results": rows}


def _browser_proxy(url):
    parsed = urlsplit(url)
    if (
        parsed.hostname != "proxy.noshadow.pro"
        or not parsed.username
        or not parsed.password
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Выбранный прокси не поддерживается сервером регистрации")
    if parsed.scheme in ("socks5", "socks5h") and parsed.port == 9696:
        userinfo = parsed.netloc.rsplit("@", 1)[0]
        url = urlunsplit(("http", userinfo + "@proxy.noshadow.pro:6969", "", "", ""))
    elif parsed.scheme != "http" or parsed.port != 6969:
        raise ValueError("Для регистрации нужен поддерживаемый HTTP-шлюз прокси")
    # Respect explicit provider session settings; add only a plain-route lease.
    return proxies.noshadow_session(url, secrets.token_hex(12))


def capabilities():
    try:
        raw = remote.request("GET", "/v1/register/capabilities", retry_busy=False)
    except remote.RemoteError as exc:
        if exc.status == 404:
            return {"modes": [], "unavailable": True}
        raise
    modes = raw.get("modes")
    if not isinstance(modes, list):
        raise ValueError("Сервер не подтвердил доступность регистрации")
    # The local fixture mode is never offered as creation of a real account.
    return {
        **{k: v for k, v in raw.items() if k != "modes"},
        "modes": [
            row
            for row in modes
            if isinstance(row, dict)
            and type(row.get("mode")) is int
            and row["mode"] in (1, 2, 3, 4)
        ],
    }


def start(body):
    if not isinstance(body, dict):
        raise ValueError("Неверные параметры регистрации")
    mode = body.get("mode", 4)
    if type(mode) is not int or mode not in (3, 4):
        raise ValueError("Выберите режим 3 или 4")
    if body.get("expected_scope") is not None and body["expected_scope"] != _owner():
        raise ValueError("Сервер или ключ изменился. Очередь регистрации остановлена")
    if body.get("unique_id") is not None:
        raise ValueError(
            "Выбор конкретного username при регистрации временно недоступен"
        )
    country = body.get("country")
    low, high = body.get("age_min", 18), body.get("age_max", 28)
    if (
        (
            country is not None
            and (not isinstance(country, str) or not re.fullmatch("[A-Z]{2}", country))
        )
        or type(low) is not int
        or type(high) is not int
        or not 18 <= low <= high <= 120
    ):
        raise ValueError("Укажите страну и возраст от 18 до 120 лет")
    for field in ("anymessage_token",):
        if not isinstance(body.get(field), str) or not body[field].strip():
            raise ValueError("Укажите прокси и ключ почтового сервиса")
    domains = body.get("domains", ["gmail.com"])
    if (
        not isinstance(domains, list)
        or not domains
        or any(
            not isinstance(d, str)
            or not re.fullmatch(r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}", d)
            for d in domains
        )
    ):
        raise ValueError("Укажите домены почты")
    domains = list(dict.fromkeys(domain.lower() for domain in domains))
    if len(domains) > 4:
        raise ValueError("Выберите не больше четырёх доменов почты")
    random.SystemRandom().shuffle(domains)
    with _lock:
        previous = _load()
        if previous and previous.get("status") not in (
            "complete",
            "failed",
            "cancelled",
        ):
            raise ValueError(
                "Предыдущее задание ещё не завершено. Проверьте его результат"
            )
        supported = capabilities()
        if country is None and supported.get("geo_policy") != "proxy_auto_v1":
            raise ValueError(
                "Сервер ещё не поддерживает автоматическую географию прокси. Регистрация не отправлена"
            )
        available = next(
            (row for row in supported["modes"] if row["mode"] == mode), None
        )
        if (
            not available
            or available.get("supported") is not True
            or available.get("available") is not True
        ):
            raise ValueError("Этот режим регистрации сейчас недоступен на сервере")
        held = None
        proxy = body.get("proxy")
        if proxy is None:
            try:
                held = proxy_pool.lease(task="registration")
                if not held.url:
                    raise ValueError(
                        "Выберите прокси для регистрации в разделе «Прокси»"
                    )
                proxy = _browser_proxy(held.url)
            except Exception:
                if held is not None:
                    held.release()
                raise
        if not isinstance(proxy, str) or not proxy:
            raise ValueError("Нужен рабочий прокси для регистрации")
        row = {
            "owner": _owner(),
            "mode": mode,
            "browser_only_state_v1": supported.get("browser_only_state_v1") is True,
            "status": "dispatch_unknown",
            "local_id": secrets.token_hex(16),
            "proxy": proxy,
            "requested_domains": domains,
        }
        if held is not None:
            _held_leases[row["local_id"]] = held
        try:
            _write(_directory() / ("request-" + row["local_id"] + ".json"), row)
            _write(
                _directory() / "current.json", row
            )  # Persist BEFORE the sole create request.
        except Exception:
            lease = _held_leases.pop(row["local_id"], None)
            if lease is not None:
                lease.release()
            raise
        try:
            result = remote.request(
                "POST",
                "/v1/register",
                retry_busy=False,
                json={
                    "mode": mode,
                    **({"country": country} if country is not None else {}),
                    "age_min": low,
                    "age_max": high,
                    "proxy": proxy,
                    "anymessage_token": body["anymessage_token"],
                    "domains": domains,
                },
            )
        except remote.RemoteError as exc:
            if (
                exc.status in (400, 401, 402, 403, 404, 422, 429)
                and not exc.outcome_unknown
            ):
                row.update(
                    status="failed", reason="Сервер не принял задание регистрации"
                )
                _remember(row)
                lease = _held_leases.pop(row["local_id"], None)
                if lease is not None:
                    lease.release()
            raise
        job = result.get("job_id")
        if not isinstance(job, str) or not _JOB.fullmatch(job):
            raise ValueError(
                "Сервер не вернул номер задания. Не повторяйте регистрацию"
            )
        row.update(job_id=job, status="queued")
        _remember(row)
        _write(_directory() / ("request-" + row["local_id"] + ".json"), row)
        return _public(row)


def _accept(row, result):
    if (
        row.get("mode") not in (3, 4)
        or result.get("account_created") is False
        or result.get("ok") is not True
    ):
        raise ValueError("Создание аккаунта не подтверждено")
    username = result.get("username")
    uid = result.get("uid")
    if (
        not isinstance(username, str)
        or not re.fullmatch(r"[A-Za-z0-9._]{2,64}", username)
        or not isinstance(uid, str)
        or not re.fullmatch(r"[1-9][0-9]{0,63}", uid)
    ):
        raise ValueError("Сервер не подтвердил владельца аккаунта")
    browser_only = result.get("state_kind") == "browser_only_v1"
    if result.get("state_kind") not in (None, "browser_only_v1"):
        raise ValueError("Сервер вернул неизвестный тип сессии")
    required = (
        ("password", "email", "browser_state")
        if browser_only
        else ("password", "email", "state", "browser_state")
    )
    if any(
        not isinstance(result.get(k), str) or not result[k].strip() for k in required
    ):
        raise ValueError("Сервер не вернул подтверждённые данные сессии")
    if browser_only and not (
        row.get("browser_only_state_v1") is True
        and result.get("same_uid_verified") is True
        and result.get("account_created") is True
        and result.get("state_saved") is True
        and "state" in result
        and "http_state" in result
        and result["state"] is None
        and result["http_state"] is None
    ):
        raise ValueError("Браузерный тип сессии не согласован с сервером")
    if row.get("owner") != _owner():
        raise ValueError("Сервер или ключ изменились. Сессия не сохранена")
    with cloud._lock(username), accounts._lock:
        account_file = paths.here(accounts.ACCOUNTS_FILE)
        previous_accounts = account_file.read_bytes() if account_file.exists() else None
        if previous_accounts is not None:
            raw = json.loads(previous_accounts)
            if not isinstance(raw, dict) or not isinstance(raw.get("accounts"), list):
                raise ValueError("Список аккаунтов не читается")
        else:
            raw = {"accounts": []}
        existing = next(
            (
                a
                for a in raw["accounts"]
                if isinstance(a, dict) and a.get("username") == username
            ),
            None,
        )
        if existing:
            from . import execution

            browser_path = client_session.state_file(username).with_suffix(
                ".browser.state"
            )
            same_browser = (
                browser_only
                and existing.get("http_disabled") is True
                and existing.get("state_kind") == "browser_only_v1"
                and existing.get("registration_uid") == uid
                and execution.store().read(username, row["mode"]) is not None
            )
            same_legacy = (
                not browser_only and client_session.state_file(username).exists()
            )
            if (
                existing.get("registration_job") == row["job_id"]
                and browser_path.exists()
                and (same_browser or same_legacy)
            ):
                if not browser_only:
                    execution.adopt_registration(
                        username, row["mode"], result["browser_state"]
                    )
                return username
            raise ValueError(
                "Такой аккаунт уже существует. Сохранённые данные не заменены"
            )
        state_path = client_session.state_file(username)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        browser_path = state_path.with_suffix(".browser.state")
        if state_path.exists() or browser_path.exists():
            raise ValueError("Состояние этого аккаунта уже существует")
        entry = {
            "username": username,
            "password": result["password"],
            "email": result["email"],
            "registration_job": row["job_id"],
            "registration_proxy": row["proxy"],
        }
        if browser_only:
            entry.update(
                http_disabled=True,
                state_kind="browser_only_v1",
                registration_mode=row["mode"],
                registration_uid=uid,
            )
        raw["accounts"].append(entry)

        def save_account():
            if row.get("owner") != _owner():
                raise ValueError("Сервер или ключ изменились. Сессия не сохранена")
            if not browser_only:
                os.chmod(state_path, 0o600)
            os.chmod(browser_path, 0o600)
            try:
                accounts._write_json(account_file, raw)
                os.chmod(account_file, 0o600)
            except Exception:
                if previous_accounts is None:
                    account_file.unlink(missing_ok=True)
                else:
                    accounts._restore_json(account_file, previous_accounts)
                raise

        from . import execution

        if browser_only:
            native_path = execution.store().path(username, row["mode"])
            if native_path.exists():
                raise ValueError("Браузерное состояние уже существует и не заменено")
            native_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            client_session.commit_cookie_import(
                browser_path,
                result["browser_state"],
                client_session.state_generation(browser_path),
                None,
                save_account,
                (native_path, None, result["browser_state"]),
            )
        else:
            client_session.commit_cookie_import(
                state_path,
                result["state"],
                client_session.state_generation(state_path),
                None,
                save_account,
                (browser_path, None, result["browser_state"]),
            )
            execution.adopt_registration(username, row["mode"], result["browser_state"])
        return username


def status():
    with _lock:
        row = _load()
        if not row:
            return {"status": "idle", "scope": _owner()}
        if not row.get("job_id") or (
            row.get("account_saved") and row.get("status") == "complete"
        ):
            return _public(row)
        result = remote.request(
            "GET", "/v1/register/" + row["job_id"], retry_busy=False
        )
        phase = result.get("status")
        if phase not in (
            "queued",
            "running",
            "complete",
            "failed",
            "cancelled",
            "interrupted_or_unknown",
        ):
            raise ValueError("Сервер вернул неизвестный статус задания")
        row["status"] = phase
        reason = result.get("reason")
        if isinstance(reason, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,95}", reason):
            row["server_reason"] = reason
        if phase in ("failed", "cancelled", "interrupted_or_unknown"):
            row["reason"] = (
                "Регистрация не подтверждена. Не повторяйте её автоматически"
            )
        if row.get("server_reason") == "browser_cleanup_unconfirmed":
            row["reason"] = (
                "Сервер не подтвердил завершение браузера. Результат регистрации требует восстановления; не повторяйте создание аккаунта"
            )
        if (
            isinstance(result.get("result"), dict)
            and result["result"].get("ok") is True
        ):
            email = result["result"].get("email")
            if isinstance(email, str) and "@" in email:
                row["email_domain"] = email.rsplit("@", 1)[1].lower()
            selection = result["result"].get("username_selection")
            if (
                isinstance(selection, dict)
                or row.get("requested_unique_id") is not None
            ):
                selection = (
                    dict(selection)
                    if isinstance(selection, dict)
                    else {
                        "requested": row.get("requested_unique_id"),
                        "status": "unknown",
                        "reason": "missing_selection_result",
                    }
                )
                allowed = {
                    "confirmed",
                    "unavailable",
                    "rejected",
                    "blocked",
                    "unknown",
                    "skipped",
                }
                if selection.get("status") not in allowed:
                    selection["status"] = "unknown"
                requested = selection.get("requested")
                if requested is not None and (
                    not isinstance(requested, str)
                    or not re.fullmatch(r"[a-z0-9_.]{2,24}", requested)
                    or requested.endswith(".")
                ):
                    requested = None
                    selection["status"] = "unknown"
                if selection.get("status") == "confirmed" and requested != result[
                    "result"
                ].get("username"):
                    selection["status"] = "unknown"
                    selection["reason"] = "username_readback_mismatch"
                row["username_selection"] = {
                    "requested": requested,
                    "status": selection["status"],
                    "reason": selection.get("reason")
                    if isinstance(selection.get("reason"), str)
                    else "invalid_selection_result",
                }
            # Recovery archive precedes any local registry/state writes.
            _write(_directory() / (row["job_id"] + ".result.json"), result["result"])
            if not row.get("account_saved"):
                try:
                    row["username"] = _accept(row, result["result"])
                    row["account_saved"] = True
                except (ValueError, OSError):
                    row["status"] = "interrupted_or_unknown"
                    row["reason"] = (
                        "Аккаунт создан, но не сохранён в списке. Данные сохранены для восстановления"
                    )
        elif phase == "complete":
            row["status"] = "interrupted_or_unknown"
            row["reason"] = "Сервер не подтвердил создание аккаунта"
        if result.get("billing_status") == "unknown" or (
            isinstance(result.get("result"), dict)
            and result["result"].get("billing_status") == "unknown"
        ):
            row["billing_status"] = "unknown"
        _remember(row)
        if phase in ("complete", "failed", "cancelled"):
            lease = _held_leases.pop(row.get("local_id"), None)
            if lease is not None:
                lease.release()
        return _public(row)


def cancel():
    with _lock:
        row = _load()
        if not row or not isinstance(row.get("job_id"), str):
            raise ValueError("Нет задания для отмены")
        remote.request(
            "POST",
            "/v1/register/" + row["job_id"] + "/cancel",
            retry_busy=False,
            json={},
        )
    return status()
