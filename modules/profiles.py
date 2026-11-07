"""Local profile storage and queued requests to the Nimbus service."""
# -*- coding: utf-8 -*-
import asyncio
import json
import re
import sqlite3
import threading
import time
from contextlib import closing

from curl_cffi import requests as crequests

from . import config
from . import db
from . import client_device as device
from . import proxies
from . import proxy_pool
from . import eventlog
from . import humanize

METHOD = "ssr"
METHODS = ("detail", "ssr")
SITE = "https://www.tiktok.com"


class ProfileError(RuntimeError):
    """Профиль не получен; текст — человеческий, для журнала и тоста."""


class ProfileInputError(ProfileError):
    """Неверный запрос (юзернейм, способ, размер пачки) — API отвечает 400."""


class ProfileIdentityError(ProfileError):
    """TikTok не признал личность сессии, и прогрев заново не помог.

    Для fetch_remote это значит: на этой личности дальше ничего не выйдет; она
    живёт один вызов и уходит с ним. Сетевые сбои и ошибки прокси сюда НЕ
    попадают — сессия в них не виновата, и прогревать её заново из-за них
    незачем. Наружу разницы нет: подкласс ProfileError, main.py так
    же отвечает 409 с человеческим текстом."""


class ProfileNetworkError(ProfileError):
    """Сеть или прокси: соединение не поднялось или оборвалось. Личность тут
    ни при чём — прогревать заново незачем, а оборванное соединение curl не
    переиспользует, так что повтор уйдёт через другой узел прокси."""


_NO_IDENTITY = "TikTok не выдал анонимную сессию — смените прокси или сделайте паузу"


def anon_proxy(recheck: bool = True) -> str:
    """Прокси запросов без входа; "" — работать нельзя (прокси выключены или
    список пуст).

    Первый живой из списка (proxy_pool.pick): личность закреплена за ним, пока
    он жив. Умер — следующий запрос получит другой прокси. Живых нет —
    ProfileNetworkError с понятным текстом. recheck=False — из event loop:
    перепроверка мёртвых блокирует, loop вставать не должен.

    Почему НЕ аренда по занятости (proxy_pool.lease), как у аккаунтов: она
    раскладывает дела по разным прокси, и анонимная личность на втором запросе
    уезжала бы на другой IP, обесценивая прогрев."""
    try:
        return proxy_pool.pick(recheck=recheck)
    except proxy_pool.NoAliveProxy as exc:
        raise ProfileNetworkError(str(exc)) from None


def _require_proxy(proxy: str) -> str:
    """Прокси анонимной личности; имена TikTok резолвит он сам, не наш DNS
    (proxies.remote_dns). Нет прокси — внятный отказ."""
    if not proxy:
        raise ProfileError("нужен прокси — включите его в разделе «Прокси»")
    return proxies.remote_dns(proxy)


def _int(v):
    """Число из statsV2 (там строки) / stats; нет значения — None."""
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _bool(v):
    return None if v is None else int(bool(v))


def _stat(info: dict, key: str):
    """statsV2 точнее stats: там строки без округления и без переполнения int32.
    user/detail опускает нулевые поля — отсутствие в полном ответе значит 0."""
    v2, v1 = info.get("statsV2") or {}, info.get("stats") or {}
    val = _int(v2.get(key))
    if val is None:
        val = _int(v1.get(key))
    return 0 if val is None and (v2 or v1) else val


def profile_row(info: dict, method: str) -> dict:
    """userInfo TikTok -> колонки таблицы profiles."""
    u = info.get("user") or {}
    return {
        "method": method,
        "user_id": u.get("id") or None,
        "sec_uid": u.get("secUid") or None,
        "unique_id": u.get("uniqueId") or None,
        "nickname": u.get("nickname") or "",
        "signature": u.get("signature") or "",
        "verified": int(bool(u.get("verified"))),
        "private_account": int(bool(u.get("privateAccount"))),
        "followers": _stat(info, "followerCount"),
        "following": _stat(info, "followingCount"),
        "friends": _stat(info, "friendCount"),
        "likes": _stat(info, "heartCount"),
        "liked": _stat(info, "diggCount"),
        "videos": _stat(info, "videoCount"),
        # только у способа ssr; у detail — NULL, а не 0: значение неизвестно
        "created_at": _int(u.get("createTime")) if method == "ssr" else None,
        "is_organization": _bool(u.get("isOrganization")) if method == "ssr" else None,
        "language": (u.get("language") or None) if method == "ssr" else None,
    }


def post_row(it: dict) -> dict:
    """Элемент itemList -> колонки таблицы posts (без username/fetched_at)."""
    v2, v1 = it.get("statsV2") or {}, it.get("stats") or {}

    def st(key):
        val = _int(v2.get(key))
        return _int(v1.get(key)) if val is None else val

    return {
        "item_id": str(it["id"]),
        "created_at": _int(it.get("createTime")),
        "description": it.get("desc") or "",
        "is_photo": int("imagePost" in it),
        "views": st("playCount"),
        "likes": st("diggCount"),
        "comments": st("commentCount"),
        "shares": st("shareCount"),
        "saves": st("collectCount"),
        "reposts": st("repostCount"),
    }


def save(username: str, info: dict, method: str) -> None:
    save_row(username, profile_row(info, method))


def save_row(username: str, row: dict) -> None:
    """Готовая строка профиля (profile_row) — в таблицу profiles."""
    row = dict(row, username=username, fetched_at=int(time.time()))
    cols = list(row)
    with closing(db.connect()) as conn:
        conn.execute(
            f"INSERT INTO profiles ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
            " ON CONFLICT(username) DO UPDATE SET "
            + ", ".join(f"{c} = excluded.{c}" for c in cols if c != "username"),
            [row[c] for c in cols])
        conn.commit()


def save_posts(username: str, items: list, shadows: dict = None) -> None:
    """Посты аккаунта заменяются целиком: удалённые с TikTok уходят и отсюда.

    shadows — {item_id: bool} с этого обновления; у поста без свежей проверки
    (старше SHADOW_MAX или проверка не удалась) остаётся прежнее значение."""
    save_post_rows(username, [post_row(it) for it in items], shadows)


def save_post_rows(username: str, rows: list, shadows: dict = None) -> None:
    """Готовые строки постов (post_row) — как save_posts."""
    now = int(time.time())
    shadows = shadows or {}
    rows = [dict(r, username=username, fetched_at=now) for r in rows]
    with closing(db.connect()) as conn:
        known = dict(conn.execute(
            "SELECT item_id, shadow FROM posts WHERE username = ?", (username,)))
        for r in rows:
            r["shadow"] = _bool(shadows[r["item_id"]]) if r["item_id"] in shadows \
                else known.get(r["item_id"])
        conn.execute("DELETE FROM posts WHERE username = ?", (username,))
        if rows:
            cols = list(rows[0])
            conn.executemany(
                f"INSERT OR REPLACE INTO posts ({', '.join(cols)})"
                f" VALUES ({', '.join('?' * len(cols))})",
                [[r[c] for c in cols] for r in rows])
        conn.commit()


def forget_recent(username: str, count: int) -> None:
    """Чистка сняла с TikTok count последних постов аккаунта — убрать их и из
    сохранённых, не дожидаясь обновления профиля.

    Суммы по постам (в тени, просмотры, лайки) считаются по этой таблице, а
    она обновляется только с профилем: без этого после чистки в строке стояло
    «постов 0, в тени 6». Чистка удаляет самые новые посты, поэтому и отсюда
    уходят самые новые; снесено всё — таблица аккаунта пустеет целиком.
    Пост, опубликованный после последнего обновления профиля, здесь ещё не
    лежит — тогда уйдёт на один старый больше, и следующее обновление профиля
    вернёт его."""
    if count <= 0:
        return
    with closing(db.connect()) as conn:
        conn.execute(
            "DELETE FROM posts WHERE item_id IN (SELECT item_id FROM posts"
            " WHERE username = ? ORDER BY created_at DESC LIMIT ?)",
            (username, count))
        conn.commit()
    _touch(username)


def save_shadows(username: str, shadows: dict) -> None:
    """Признак тени {item_id: bool} уже сохранённым постам аккаунта."""
    if not shadows:
        return
    with closing(db.connect()) as conn:
        conn.executemany(
            "UPDATE posts SET shadow = ? WHERE username = ? AND item_id = ?",
            [(_bool(flag), username, item_id) for item_id, flag in shadows.items()])
        conn.commit()


def _bool_or_none(v):
    return None if v is None else bool(v)


def _profile_json(row) -> dict:
    """Строка profiles (+ суммы постов из запроса) -> JSON для API: флаги
    булевы, неизвестное (поля только ssr у способа detail) — null."""
    r = dict(row)
    return {
        "username": r["username"],
        "user_id": r["user_id"],
        "sec_uid": r["sec_uid"],
        "nickname": r["nickname"],
        "signature": r["signature"],
        "verified": _bool_or_none(r["verified"]),
        "private_account": _bool_or_none(r["private_account"]),
        "followers": r["followers"],
        "following": r["following"],
        "friends": r["friends"],
        "likes": r["likes"],
        "liked": r["liked"],
        "videos": r["videos"],
        "created_at": r["created_at"],
        "is_organization": _bool_or_none(r["is_organization"]),
        "language": r["language"],
        "posts": {
            "count": r["posts_count"] or 0,
            "views": r["posts_views"] or 0,
            "likes": r["posts_likes"] or 0,
            "comments": r["posts_comments"] or 0,
            "shares": r["posts_shares"] or 0,
            "saves": r["posts_saves"] or 0,
            # постов в тени; null — ни один пост ещё не проверяли
            "shadow": (r["posts_shadow"] or 0) if r["posts_checked"] else None,
        },
        "method": r["method"],
        "fetched_at": r["fetched_at"],
    }


_PROFILE_SELECT = (
    "SELECT p.*, COUNT(s.item_id) AS posts_count, SUM(s.views) AS posts_views,"
    " SUM(s.likes) AS posts_likes, SUM(s.comments) AS posts_comments,"
    " SUM(s.shares) AS posts_shares, SUM(s.saves) AS posts_saves,"
    " SUM(s.shadow) AS posts_shadow, COUNT(s.shadow) AS posts_checked"
    " FROM profiles p LEFT JOIN posts s ON s.username = p.username")


def get(username: str):
    """Профиль из базы (JSON API) или None."""
    try:
        with closing(db.connect()) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(_PROFILE_SELECT + " WHERE p.username = ? GROUP BY p.username",
                               (username,)).fetchone()
    except sqlite3.Error:
        return None
    return _profile_json(row) if row else None


def get_many(usernames: list) -> dict:
    """{username: профиль JSON API} одним запросом; кого нет в базе — нет и в ответе."""
    out = {}
    if not usernames:
        return out
    try:
        with closing(db.connect()) as conn:
            conn.row_factory = sqlite3.Row
            for i in range(0, len(usernames), 500):  # потолок переменных SQLite
                part = usernames[i:i + 500]
                rows = conn.execute(
                    _PROFILE_SELECT + f" WHERE p.username IN ({', '.join('?' * len(part))})"
                    " GROUP BY p.username", part).fetchall()
                out.update((r["username"], _profile_json(r)) for r in rows)
    except sqlite3.Error:
        pass
    return out


def list_all() -> list:
    """Все сохранённые профили (JSON API), по юзернейму."""
    try:
        with closing(db.connect()) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(_PROFILE_SELECT + " GROUP BY p.username"
                                " ORDER BY p.username").fetchall()
    except sqlite3.Error:
        return []
    return [_profile_json(r) for r in rows]


def posts_of(username: str) -> list:
    """Посты аккаунта из базы (JSON API), новые первыми."""
    try:
        with closing(db.connect()) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT item_id, created_at, description, is_photo, views, likes,"
                " comments, shares, saves, reposts, shadow, fetched_at FROM posts"
                " WHERE username = ? ORDER BY created_at DESC", (username,)).fetchall()
    except sqlite3.Error:
        return []
    out = []
    for r in rows:
        d = dict(r)
        d["is_photo"] = bool(d["is_photo"])
        d["shadow"] = _bool_or_none(d["shadow"])
        d["url"] = f"{SITE}/@{username}/{'photo' if d['is_photo'] else 'video'}/{d['item_id']}"
        out.append(d)
    return out


def summaries() -> dict:
    """{username: профиль JSON API} — для поля stats в /api/accounts."""
    return {p["username"]: p for p in list_all()}


# --- прогон пачки юзернеймов: синхронно (fetch_now) и фоном (start) ---

# потолок синхронного POST /api/profiles/fetch: больше — фоном через refresh
FETCH_NOW_MAX = 50

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.]{1,64}$")


def clean_usernames(usernames) -> list:
    """Юзернеймы без @ и пробелов, без повторов; неверный — ProfileError."""
    if isinstance(usernames, str):
        usernames = [usernames]
    if not isinstance(usernames, (list, tuple)):
        raise ProfileInputError("usernames: список строк")
    out = []
    for n in usernames:
        name = str(n or "").strip().lstrip("@")
        if not _USERNAME_RE.match(name):
            raise ProfileInputError(f"неверный юзернейм {n!r}")
        if name not in out:
            out.append(name)
    if not out:
        raise ProfileInputError("нет юзернеймов")
    return out


def _check_method(method):
    method = method or METHOD
    if method not in METHODS:
        raise ProfileInputError(f"method: одно из {', '.join(METHODS)}")
    return method


def _run_batch(names: list, method: str, with_posts: bool,
               on_start=None, on_done=None, more=None) -> None:
    """Пачка профилей: собирает наш сервер (modules/cloud.py)."""
    _batch_via_server(names, method, with_posts, on_start, on_done, more)


def _batch_via_server(names: list, method: str, with_posts: bool,
                      on_start=None, on_done=None, more=None) -> None:
    """Профили собирает сервер: сюда приходят готовые строки, они ложатся в
    data.db, аватарка качается отсюда — без подписей."""
    from . import cloud, remote
    proxy = anon_proxy(recheck=False)
    queue = list(names)

    def done(name: str, reason: str = "") -> None:
        if reason:
            print(f"[profile] {name}: {reason}")
            eventlog.say(f"профиль не обновлён: {reason}", "err", name, "profile")
        if on_done:
            on_done(name, reason)

    while True:
        if not queue and more:
            queue.extend(more())
        if not queue:
            return
        chunk, queue = queue[:FETCH_NOW_MAX], queue[FETCH_NOW_MAX:]
        for name in chunk:
            if on_start:
                on_start(name)
        try:
            out = cloud.profiles(chunk, proxy, method, with_posts,
                                 min(config.threads(), 16))
        except remote.RemoteError as exc:
            for name in chunk:
                done(name, str(exc))
            continue
        for p in out["profiles"]:
            name = p["username"]
            save_row(name, p["profile"])
            if p["posts"] is not None:
                shadows = {r["item_id"]: r["shadow"] for r in p["posts"]
                           if r.get("shadow") is not None}
                save_post_rows(name, [{k: v for k, v in r.items() if k != "shadow"}
                                      for r in p["posts"]], shadows)
            _touch(name)
            if p["avatar_url"]:
                _avatar_via(name, p["avatar_url"], proxy)
            done(name)
        for f in out["failed"]:
            done(f["username"], f["reason"])


def _avatar_via(name: str, url: str, proxy: str) -> None:
    """Аватарка по ссылке с сервера: CDN подписей не просит, качаем сами."""
    from . import avatars
    src = avatars.source_of(url)
    if src and src == avatars.stored_source(name):
        return
    try:
        with crequests.Session(impersonate=device.IMPERSONATE,
                               proxies={"all": proxies.remote_dns(proxy)}) as s:
            r = s.get(url, timeout=(10, 30))
    except Exception as exc:  # noqa: BLE001 — без аватарки профиль всё равно готов
        print(f"[profile] {name}: аватарка не скачалась — {exc}")
        return
    if r.status_code == 200 and avatars.store(name, r.content,
                                              r.headers.get("content-type", ""), src):
        _touch(name, avatar=True)


def fetch_now(usernames, method: str = None, with_posts: bool = True) -> dict:
    """Забрать профили сейчас и дождаться (POST /api/profiles/fetch).
    Возвращает {"profiles": [JSON API], "failed": [{username, reason}]}."""
    method = _check_method(method)
    names = clean_usernames(usernames)
    if len(names) > FETCH_NOW_MAX:
        raise ProfileInputError(f"за раз не больше {FETCH_NOW_MAX} — остальное через refresh")
    _require_proxy(anon_proxy())  # внятный отказ до всякой работы
    failed = []
    _run_batch(names, method, with_posts,
               on_done=lambda n, reason: reason and failed.append(
                   {"username": n, "reason": reason}))
    bad = {f["username"] for f in failed}
    return {"profiles": [p for p in (get(n) for n in names if n not in bad) if p],
            "failed": failed}


_lock = threading.Lock()
# имена, докинутые в уже идущее обновление: их забирает свободная дорожка
_queued = []
# pending — ещё не готовые имена (в работе и в очереди): спиннеры на строках
# с первой секунды, а не с момента, когда имя дойдёт до потока
_state = {"running": False, "total": 0, "done": 0, "ok": 0, "current": [],
          "pending": [], "failed": [], "error": "", "method": METHOD, "posts": True,
          "started_at": None, "finished_at": None}


# что поменялось — для живого потока UI (GET /api/stream в main.py): сквозной
# номер изменения и на каком номере аккаунт менялся последний раз. Поток шлёт
# только строки, поменявшиеся после его прошлой отправки; seq в статусе —
# чтобы UI отличал свежий снимок от опоздавшего. Начинается с текущего
# времени в микросекундах, а не с нуля: после перезапуска сервера номера
# растут дальше, и открытая страница не примет новые снимки за старые
_change_seq = time.time_ns() // 1000
_changed = {}         # username -> номер изменения профиля или постов
_avatar_changed = {}  # username -> номер новой аватарки


def _status_locked() -> dict:
    st = json.loads(json.dumps(_state))
    st["seq"] = _change_seq
    return st


def status() -> dict:
    with _lock:
        return _status_locked()


def _touch(name: str = "", avatar: bool = False) -> None:
    """Поменялся аккаунт name или ход обновления — будим живой поток UI."""
    global _change_seq
    with _lock:
        _change_seq += 1
        if name:
            (_avatar_changed if avatar else _changed)[name] = _change_seq
    eventlog.pulse("profiles")


def changes(since: int) -> dict:
    """Всё, что поменялось после номера since, для живого потока UI:
    {"seq", "status", "profiles": {username: JSON API или None, если профиля
    уже нет}, "avatars": {username: {"data": data URI, "at": время}}}.
    Следующий вызов — с полученным seq."""
    from . import avatars
    with _lock:
        st = _status_locked()
        names = [n for n, seq in _changed.items() if seq > since]
        faces = [n for n, seq in _avatar_changed.items() if seq > since]
    found = get_many(names)
    return {"seq": st["seq"], "status": st,
            "profiles": {n: found.get(n) for n in names},
            "avatars": avatars.data_of(faces)}


def start(usernames, method: str = None, with_posts: bool = True) -> dict:
    """Фоновое обновление (POST /api/profiles/refresh). ProfileError — нет
    прокси, неверные юзернеймы (проверяем до потока, чтобы ответить сразу).

    Обновление уже идёт — не отказ: имена уходят в его очередь. Обновление
    одного аккаунта ничем не мешает другому, и запрещать второй нажим незачем;
    те, кто уже в очереди, второй раз не встают."""
    method = _check_method(method)
    names = clean_usernames(usernames)
    _require_proxy(anon_proxy())
    with _lock:
        if _state["running"]:
            fresh = [n for n in names if n not in _state["pending"]]
            _queued.extend(fresh)
            _state["pending"].extend(fresh)
            _state["total"] += len(fresh)
            st = _status_locked()
        else:
            st = None
    if st is not None:
        _touch()
        return st
    with _lock:
        _state.update(running=True, total=len(names), done=0, ok=0, current=[],
                      pending=list(names), failed=[], error="", method=method, posts=with_posts,
                      started_at=int(time.time()), finished_at=None)
    _touch()
    # поток остаётся, хотя работа теперь и так уходит в чужой loop: он нужен,
    # чтобы запрос отвечал сразу, и чтобы весь учёт _state (включая finally со
    # сбросом running) остался одним читаемым куском, а не разъехался по колбэкам
    threading.Thread(target=_run_thread, args=(names, method, with_posts),
                     name="profile-refresh", daemon=True).start()
    return status()


def _on_start(name: str) -> None:
    with _lock:
        _state["current"].append(name)


def _on_done(name: str, reason: str) -> None:
    with _lock:
        _state["current"].remove(name)
        _state["pending"].remove(name)
        _state["done"] += 1
        if reason:
            _state["failed"].append({"username": name, "reason": reason})
        else:
            _state["ok"] += 1
    _touch()


def _take_queued() -> list:
    """Имена, добавленные в идущее обновление с прошлого раза."""
    with _lock:
        names, _queued[:] = list(_queued), []
    return names


def _run_thread(names: list, method: str, with_posts: bool) -> None:
    print(f"[profile] обновляю профили: {len(names)},"
          f" одновременно до {config.threads()}")
    eventlog.say(f"обновление профилей: {len(names)}", "", source="profile")
    try:
        while names:
            _run_batch(names, method, with_posts, _on_start, _on_done,
                       more=_take_queued)
            # имя могли докинуть ровно между концом дорожек и этой строкой
            names = _take_queued()
    except Exception as exc:  # noqa: BLE001 — поток не должен умирать молча
        reason = str(exc) if isinstance(exc, ProfileError) else humanize.error(exc)
        with _lock:
            _state["error"] = reason
        print(f"[profile] обновление прервано: {type(exc).__name__}: {exc}")
        eventlog.say(f"обновление профилей прервано: {reason}", "err", source="profile")
    finally:
        with _lock:
            # прогон оборвался — недоделанные имена в итог не считаем, иначе
            # в отчёте осталось бы «обновлено 3 из 50»
            _queued[:] = []
            _state.update(running=False, current=[], pending=[],
                          total=_state["total"] - len(_state["pending"]),
                          finished_at=int(time.time()))
        _touch()
        st = status()
        print(f"[profile] готово: {st['ok']} из {st['total']}")
        eventlog.say(f"профили обновлены: {st['ok']} из {st['total']}",
                     "ok" if st["ok"] == st["total"] else "warn", source="profile")
