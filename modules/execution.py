"""Explicit browser execution contract, independent of legacy HTTP routing.

Callers own browser state separately from legacy HTTP sessions. No executor
fallback, persistent settings, credential logging or implicit mode selection.
"""

import base64
import contextlib
import json
import re
import threading
import time
from pathlib import Path

from . import config, paths, remote
from .browser_states import BrowserStates

ROOT = "/v3/browser"
OPERATIONS = ("login", "publish", "logout")
_locks = {}
_guard = threading.Lock()


def selected(operation):
    modes = config.get("execution_modes", {})
    mode = modes.get(operation, 0) if isinstance(modes, dict) else None
    if type(mode) is not int or mode not in (0, 3, 4):
        raise ExecutorUnavailable("Выбранный режим недоступен")
    return mode


def store(kind="browser"):
    if kind not in ("browser", "browser-companion", "browser-jobs"):
        raise ValueError("Unknown state namespace")
    namespace = remote.base() + "\n" + remote.key()
    return BrowserStates(paths.here(Path(__file__).resolve().parent.parent / "sessions" / kind), namespace)


def adopt_registration(username, mode, browser_state):
    """Explicit mode-bound import; keep the HTTP companion in its own store."""
    states = store()
    if states.read(username, mode) is None:
        states.write(username, mode, browser_state)


def account_status(username):
    states = store()
    return {str(mode): {"saved": states.read(username, mode) is not None}
            for mode in (3, 4)}


def stage_media(username, blobs, kind):
    mode = selected("publish")
    if mode not in (3, 4):
        raise ExecutorUnavailable("Браузерный режим публикации не выбран")
    row = next(row for row in capabilities()["operations"]["publish"] if row["mode"] == mode)
    if not row["available"]:
        raise ExecutorUnavailable(row["reason"])
    if config.get("browser_visibility", "public") != "private":
        raise ExecutorUnavailable("Для этого браузерного исполнителя явно выберите приватную публикацию")
    if not blobs or any(not isinstance(blob, bytes) or not blob for blob in blobs):
        raise ValueError("Пустой или неверный медиафайл")
    if sum(len(blob) for blob in blobs) > 100 * 1024 * 1024:
        raise ValueError("Размер браузерной публикации должен быть до 100 МиБ")
    if kind not in ("photo", "video") or kind == "video" and len(blobs) != 1:
        raise ValueError("Неверный набор медиафайлов")
    return [{"browser_mode": mode, "browser_owner": username,
             "browser_namespace": str(store().root), "browser_kind": kind,
             "browser_file": {"name": f"media-{index}." + ("mp4" if kind == "video" else "jpg"),
                              "content_base64": base64.b64encode(blob).decode("ascii")}}
            for index, blob in enumerate(blobs)]


def publish_staged(username, proxy, items, caption):
    mode = selected("publish")
    if not items or any(not isinstance(item, dict) or item.get("browser_mode") != mode
                        or item.get("browser_owner") != username
                        or item.get("browser_namespace") != str(store().root) for item in items):
        raise ExecutorUnavailable("Режим или сервер изменился после подготовки медиа")
    visibility = config.get("browser_visibility", "public")
    if visibility != "private":
        raise ExecutorUnavailable("Для этого браузерного исполнителя явно выберите приватную публикацию")
    return run_account("publish", mode, username, proxy, caption=caption, visibility=visibility,
                       files=[item["browser_file"] for item in items])


class ExecutorUnavailable(ValueError):
    pass


@contextlib.contextmanager
def _exclusive(lock):
    if not lock.acquire(blocking=False):
        raise ExecutorUnavailable("Операция аккаунта уже выполняется. Дождитесь её результата.")
    try:
        yield
    finally:
        lock.release()


def capabilities():
    """A failed negotiation offers no executable modes."""
    try:
        raw = remote.request("GET", ROOT + "/capabilities", retry_busy=False)
    except remote.RemoteError:
        raw = {}
    operations = raw.get("operations", {}) if isinstance(raw, dict) else {}
    result = {}
    for operation in OPERATIONS:
        rows = operations.get(operation, []) if isinstance(operations, dict) else []
        rows = rows if isinstance(rows, list) else []
        modes = []
        for mode in range(1, 5):
            matches = [row for row in rows if isinstance(row, dict)
                       and type(row.get("mode")) is int and row["mode"] == mode]
            row = matches[0] if len(matches) == 1 and mode in (3, 4) else {}
            modes.append({"mode": mode, "supported": row.get("supported") is True,
                          "available": row.get("supported") is True and row.get("available") is True,
                          "live_proven": row.get("live_proven") is True,
                          "reason": row.get("reason") if isinstance(row.get("reason"), str)
                          else "Режим недоступен на сервере"})
        result[operation] = modes
    return {"operations": result}


def execute(operation, mode, payload, *, before_submit=None):
    """Negotiate the exact operation before sending one explicit mutation.

    State is opaque and must remain in a separate browser/mode namespace.
    Registration has its own contract and is deliberately absent here.
    """
    if operation not in OPERATIONS:
        raise ValueError("Неизвестная операция")
    if type(mode) is not int or mode not in (3, 4):
        raise ExecutorUnavailable("Режим не поддерживается браузерным исполнителем")
    if not isinstance(payload, dict) or "mode" in payload:
        raise ValueError("Режим задаётся отдельно от данных операции")
    row = next(row for row in capabilities()["operations"][operation] if row["mode"] == mode)
    if not row["available"]:
        raise ExecutorUnavailable(row["reason"])
    if operation == "publish" and payload.get("visibility") != "private":
        raise ValueError("Браузерная публикация требует явного visibility=private")
    if before_submit is not None:
        before_submit()
    result = remote.request("POST", ROOT + "/" + operation,
                            json={**payload, "mode": mode}, timeout=(10, 80), retry_busy=False)
    if (not isinstance(result, dict) or result.get("operation") != operation
            or type(result.get("mode")) is not int or result["mode"] != mode
            or not isinstance(result.get("job_id"), str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", result["job_id"])):
        raise remote.RemoteError("Сервер не подтвердил задание. Не повторяйте операцию.",
                                 stop_account=True, outcome_unknown=True)
    return {"job_id": result["job_id"], "operation": operation, "mode": mode}


def job(job_id):
    if not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", job_id):
        raise ValueError("Неверный номер задания")
    return remote.request("GET", ROOT + "/jobs/" + job_id, retry_busy=False)


def cancel(job_id):
    if not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", job_id):
        raise ValueError("Неверный номер задания")
    return remote.request("POST", ROOT + "/jobs/" + job_id + "/cancel", retry_busy=False)


def run_account(operation, mode, username, proxy, **payload):
    """Resume an admitted job after transport errors; never submit it twice."""
    states, companion, pending = store(), store("browser-companion"), store("browser-jobs")
    lock_key = str(states.path(username, mode))
    with _guard:
        lock = _locks.setdefault(lock_key, threading.Lock())
    with _exclusive(lock):
        saved_job = pending.read(username, mode)
        if saved_job:
            admitted = json.loads(saved_job)
            if admitted.get("operation") != operation or not admitted.get("job_id"):
                raise ExecutorUnavailable("Сначала проверьте незавершённую операцию аккаунта")
        else:
            browser_state = states.read(username, mode)
            if operation != "login" and not browser_state:
                raise ExecutorUnavailable("Сначала выполните вход в выбранном браузерном режиме")
            body = {**payload, "username": username, "proxy": proxy}
            if browser_state:
                body["browser_state"] = browser_state
            state = companion.read(username, mode)
            if state:
                body["state"] = state
            try:
                admitted = execute(operation, mode, body, before_submit=lambda: pending.write(
                    username, mode, json.dumps({"operation": operation, "mode": mode,
                                                "dispatch_unknown": True})))
            except remote.RemoteError as exc:
                if exc.status in (400, 401, 402, 403, 404, 422, 429) and not exc.outcome_unknown:
                    pending.path(username, mode).unlink(missing_ok=True)
                raise
            # Persist the accepted job before polling. The record has no secrets.
            pending.write(username, mode, json.dumps(admitted))
        deadline = time.monotonic() + 900
        while True:
            envelope = job(admitted["job_id"])
            if not isinstance(envelope, dict):
                raise remote.RemoteError("Неверный статус задания", stop_account=True, outcome_unknown=True)
            phase = envelope.get("status")
            if phase not in ("queued", "running", "complete", "failed", "cancelled", "interrupted_or_unknown"):
                raise remote.RemoteError("Неизвестный статус задания", stop_account=True, outcome_unknown=True)
            if phase not in ("queued", "running"):
                break
            if time.monotonic() >= deadline:
                raise remote.RemoteError("Задание ещё выполняется. Проверьте его результат.",
                                         stop_account=True, outcome_unknown=True)
            time.sleep(1)
        result = envelope.get("result")
        if not isinstance(result, dict) or type(result.get("ok")) is not bool:
            raise remote.RemoteError("Результат операции не подтверждён. Не повторяйте её.",
                                     stop_account=True, outcome_unknown=True)
        if result.get("state_owner") != username:
            raise remote.RemoteError("Владелец состояния не подтверждён", stop_account=True, outcome_unknown=True)
        if result["ok"] and result.get("verdict") != "ok":
            raise remote.RemoteError("Успех операции не подтверждён", stop_account=True, outcome_unknown=True)
        if operation == "login" and result["ok"] and (type(result.get("uid")) not in (str, int)
                or not re.fullmatch(r"[1-9][0-9]{0,63}", str(result["uid"]))):
            raise remote.RemoteError("Сервер не подтвердил UID вошедшего аккаунта", stop_account=True, outcome_unknown=True)
        if operation == "publish" and result["ok"] and not re.fullmatch(r"[1-9][0-9]{0,63}", str(result.get("item_id", ""))):
            raise remote.RemoteError("Сервер не подтвердил номер публикации", stop_account=True, outcome_unknown=True)
        if operation == "logout" and type(result.get("confirmed")) is not bool:
            raise remote.RemoteError("Выход не подтверждён", stop_account=True, outcome_unknown=True)
        public_fields = {"ok", "verdict", "reason", "message", "code", "uid", "username",
                         "item_id", "confirmed", "mutation_started", "state_saved", "state_owner"}
        out = {k: v for k, v in result.items() if k in public_fields}
        if operation == "logout":
            if states.clear_confirmed(username, mode, result):
                companion.path(username, mode).unlink(missing_ok=True)
        else:
            token = result.get("browser_state")
            if isinstance(token, str) and token.strip() and result.get("state_saved") is not False:
                states.write(username, mode, token)
                if isinstance(result.get("state"), str) and result["state"].strip():
                    companion.write(username, mode, result["state"])
            elif result["ok"]:
                out.update(state_saved=False, stop_account=True)
                if operation == "login":
                    out.update(ok=False, reason="Не удалось сохранить подтверждённый браузерный вход")
        if phase == "complete" and result.get("verdict") in ("ok", "rejected"):
            pending.path(username, mode).unlink(missing_ok=True)
        else:
            out.update(stop_account=True)
        out.update(network=False, retriable=False)
        if out.get("verdict") == "unknown":
            out["stop_account"] = True
        if not out.get("ok"):
            out.setdefault("reason", "Операция не подтверждена")
        return out
