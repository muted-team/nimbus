# -*- coding: utf-8 -*-
"""Чистка постов аккаунта через наш сервер — одна на ручную чистку и кампанию.

Раньше «снести N последних постов» было написано дважды (маршрут в main.py и
воркер кампании), а ручная чистка и кампания проверяли друг друга без общего
замка. Здесь одна реализация и один список «кто сейчас чистится»: аккаунт берут
через `claim`, возвращают через `release`, и двое разом на одном аккаунте
не окажутся.

Итог чистки уходит подписчикам (`on_result`): main.py правит по нему числа
студии. Формат итога: {"deleted", "total"} или {"error"}.
"""
import threading
import time

_lock = threading.Lock()
_active: dict = {}       # username -> время старта: кто чистится прямо сейчас
# итог последней чистки по аккаунту. Ручная чистка идёт фоном, HTTP-ответ
# приходит до её конца — без итога морда считала бы удавшейся любую принятую
# задачу и писала «очищено N из N» даже после сбоя.
_results: dict = {}
_RESULTS_MAX = 100
_listeners: list = []


def claim(usernames) -> tuple:
    """Занять аккаунты под чистку разом, под одним замком.
    Возвращает (взятые, занятые): занятые уже чистятся кем-то другим."""
    taken, busy = [], []
    with _lock:
        for username in usernames:
            if username in _active:
                busy.append(username)
            else:
                _active[username] = int(time.time())
                taken.append(username)
    return taken, busy


def release(username: str) -> None:
    with _lock:
        _active.pop(username, None)


def current() -> list:
    with _lock:
        return sorted(_active)


def status() -> dict:
    """Что отдаёт GET /api/accounts/purge: какие чистки идут и чем кончились
    последние (web/src/api/types.ts, PurgeStatus)."""
    with _lock:
        current_now = sorted(_active)
        results = dict(_results)
    return {"running": len(current_now), "current": current_now, "results": results}


def on_result(callback) -> None:
    """Подписаться на итоги чисток: callback(username, result)."""
    if callback not in _listeners:
        _listeners.append(callback)


def note(username: str, result: dict) -> None:
    """Записать итог чистки и сообщить подписчикам."""
    with _lock:
        _results.pop(username, None)
        _results[username] = result
        while len(_results) > _RESULTS_MAX:
            _results.pop(next(iter(_results)))
    for cb in list(_listeners):
        try:
            cb(username, result)
        except Exception as exc:  # noqa: BLE001 — подписчик не должен ронять чистку
            print("[purge] %s: слушатель чистки упал: %s" % (username, exc))


def run_one(username: str, proxy_url, count) -> dict:
    """Снести count последних постов (-1 / "all" — все) через сервер.
    Возвращает {deleted, failed, total}; сбой записывает в итог и пробрасывает.
    Аккаунт вызывающий уже взял через claim."""
    from . import cloud, humanize, remote
    try:
        res = cloud.delete_posts(username, proxy_url, count=count)
        if (res.get("stop_account") or res.get("state_saved") is False
                or res.get("verdict") in ("unknown", "blocked")):
            raise remote.RemoteError(res.get("message") or "Удаление не подтверждено. Обработка аккаунта остановлена.",
                                     stop_account=True, outcome_unknown=res.get("verdict") == "unknown")
    except Exception as exc:  # noqa: BLE001 — итог нужен и при сбое
        note(username, {"error": humanize.error(exc)})
        raise
    note(username, {"deleted": res["deleted"], "total": res["total"]})
    return res


def run_manual(username: str, count) -> None:
    """Ручная чистка в фоновом потоке: берёт прокси, чистит, пишет в журнал.
    Аккаунт уже взят через claim; возвращается он здесь."""
    from . import eventlog, humanize, proxy_pool
    held = None
    try:
        # наименее занятый живой прокси; умрёт посреди чистки — сессия
        # пересядет на другой. Нет прокси — итог со сбоем пишем сами: до
        # run_one дело не дошло.
        try:
            held = proxy_pool.lease()
        except Exception as exc:  # noqa: BLE001
            note(username, {"error": humanize.error(exc)})
            raise
        print("[purge] %s: прокси %s" % (
            username, proxy_pool.short(held.url) if held.url else "выключен"))
        res = run_one(username, held.url, count)
        print("[purge] %s: удалено %d из %d" % (username, res["deleted"], res["total"]))
        if res["total"]:
            eventlog.say("удалено постов: %d из %d" % (res["deleted"], res["total"]),
                         "ok" if res["deleted"] == res["total"] else "warn",
                         username, "delete")
        else:
            eventlog.say("удалять нечего — постов нет", "", username, "delete")
    except Exception as exc:  # noqa: BLE001 — фон, падать некуда
        print("[purge] %s: не вышло (%s: %s)" % (username, type(exc).__name__, exc))
        eventlog.say("посты не удалены: %s" % humanize.error(exc),
                     "err", username, "delete")
    finally:
        if held is not None:
            held.release()
        release(username)
