"""HTTP client for the Nimbus API service."""
# -*- coding: utf-8 -*-
import base64
import contextlib
import json
import re
import secrets
import tempfile
import threading
from pathlib import Path

from curl_cffi import requests

from . import client_device as device
from . import client_session as session_manager
from . import media_info, proxies, remote, tos_transfer as tos_upload

# вход с кодом из почты и удаление всех постов идут минутами
LONG = (10, 900)

_locks = {}
_locks_guard = threading.Lock()






def enabled() -> bool:
    """Через наш сервер — всегда, кроме самого сервера. Режима «на месте» у
    клиента нет ни в сборке, ни в копии из репозитория."""
    return True


def _lock(username: str) -> threading.Lock:
    # запросы одного аккаунта — по одному: иначе два ответа принесут две
    # новые строки состояния, и одна затрёт другую
    with _locks_guard:
        return _locks.setdefault(username, threading.Lock())


state_file = session_manager.state_file


def import_cookies(text: str) -> dict:
    """Resolve the owner with the server, then verify a state bound to that owner."""
    from . import proxy_pool
    cookies = session_manager.normalize_cookie_import(text)
    initial_states = session_manager.cookie_import_snapshot()
    with contextlib.ExitStack() as cleanup, tempfile.TemporaryDirectory(prefix='ttwa-cookie-') as tmp:
        held = proxy_pool.lease(task='login')
        cleanup.callback(held.release)
        if not held.url:
            raise ValueError('Для проверки куки нужен прокси')
        device_path = Path(tmp) / 'device.json'
        alias = 'cookie_' + secrets.token_hex(8)
        via = session_manager.sticky_proxy(held.url, alias, device_path=device_path)
        device_text = device_path.read_text() if device_path.exists() else ''

        def verify(username):
            imported = remote.request('POST', '/v1/accounts/import', retry_busy=False,
                                      json={'username': username, 'cookies': cookies, 'device': device_text})
            token = imported.get('state')
            if not isinstance(token, str) or not token:
                raise ValueError('Сервер не подтвердил импорт куки')
            response = remote.request('POST', '/v1/session/check', retry_busy=False,
                                      json={'username': username, 'state': token, 'proxy': via})
            data = response.get('data') or {}
            owner = data.get('username')
            uid = data.get('uid')
            if (data.get('alive') is not True or data.get('message') != 'success'
                    or not isinstance(owner, str) or not owner
                    or not uid):
                raise ValueError('Сессия по куки не подтверждена TikTok')
            owner = owner.lstrip('@')
            if not re.fullmatch(r'[A-Za-z0-9_.]{2,24}', owner):
                raise ValueError('TikTok вернул неверный логин аккаунта')
            token = response.get('state')
            if not isinstance(token, str) or not token:
                raise ValueError('Сервер не вернул состояние аккаунта')
            return owner, str(uid), token

        owner, uid, _ = verify(alias)
        with _lock(owner):
            path = state_file(owner)
            generation, previous = initial_states.get(path, (0, None))
            confirmed_owner, confirmed_uid, token = verify(owner)
            if confirmed_owner != owner or confirmed_uid != uid:
                raise ValueError('Аккаунт куки изменился при проверке')
            local_device = session_manager.device_file(owner)
            _, device_previous = initial_states.get(local_device, (0, None))
            try:
                kept_device = json.loads(device_previous) if device_previous is not None else {}
                if not isinstance(kept_device, dict):
                    raise ValueError
            except (TypeError, ValueError):
                raise ValueError('Сохранённые параметры аккаунта не читаются') from None
            route = json.loads(device_text).get('noshadow_sticky') if device_text else None
            if route:
                kept_device['noshadow_sticky'] = route
            return {'username': owner, 'state': token, 'generation': generation,
                    'previous_state': previous,
                    'device_update': (local_device, device_previous, json.dumps(kept_device)) if route else None}


def _write(f: Path, token: str, generation: int = None) -> bool:
    """Поздний ответ не восстанавливает забытое или переименованное состояние."""
    if generation is None:
        generation = session_manager.state_generation(f)
    return session_manager.write_state_if_current(f, token, generation)


def _save(username: str, token: str, generation: int = None) -> bool:
    if token:
        return _write(state_file(username), token, generation) is not False
    return True


def _generation_current(path: Path, generation: int) -> None:
    if session_manager.state_generation(path) != generation:
        raise remote.RemoteError("Состояние аккаунта изменено. Поздний ответ не сохранён.",
                                 stop_account=True)


def _state(username: str, generation: int = None) -> str:
    """Строка состояния аккаунта; прежняя сессия переносится на сервер. Нет
    ни того, ни другого — ""."""
    f = state_file(username)
    if generation is None:
        generation = session_manager.state_generation(f)
    _generation_current(f, generation)
    if f.exists():
        return f.read_text(encoding="utf-8").strip()
    jar = session_manager.session_file(username)
    if not jar.exists():
        return ""
    dev = jar.with_name(jar.name[:-len(session_manager.SESSION_SUFFIX)]
                        + session_manager.DEVICE_SUFFIX)
    out = remote.request("POST", "/v1/accounts/import", json={
        "username": username, "cookies": jar.read_text(encoding="utf-8"),
        "device": dev.read_text(encoding="utf-8") if dev.exists() else ""})
    if not _save(username, out.get("state"), generation):
        raise remote.RemoteError("Состояние аккаунта изменено. Импорт не сохранён.", stop_account=True)
    return out.get("state") or ""


# Сервер не может прочесть строку состояния: её шифровал другой ключ
# (тестовый сервер или ключ сменили). Строку выбрасываем — _state перенесёт
# вход заново из прежней сессии sessions/<имя>.json, и запрос повторяется.
STALE = 409


def _stale_retry(username: str, send, generation: int = None):
    """send(token) один раз с текущей строкой; 409 — выбросить её и ещё раз
    со строкой, перенесённой из прежней сессии."""
    auth = state_file(username)
    kept = session_manager.device_state_file(username)
    if generation is None:
        generation = session_manager.state_generation(auth)
    kept_generation = session_manager.state_generation(kept)
    try:
        return send(_state(username, generation))
    except remote.RemoteError as exc:
        if exc.status != STALE:
            raise
        print(f"[cloud] {username}: строка состояния не читается сервером — "
              "переношу вход из прежней сессии")
        # компьютер без входа шифровал тот же ключ — его сервер не прочтёт тоже
        if not session_manager.remove_states_if_current(((auth, generation), (kept, kept_generation))):
            raise remote.RemoteError("Состояние аккаунта изменено. Поздний ответ не сохранён.",
                                     stop_account=True) from None
        return send(_state(username, generation))


def _call(username: str, path: str, body: dict, timeout=LONG) -> dict:
    protected = remote._protected("POST", path)
    publication = path.rstrip("/").endswith("/publish")
    upload = path.rstrip("/").endswith("/upload")
    if body.get("proxy"):
        body = {**body, "proxy": session_manager.sticky_proxy(body["proxy"], username)}

    def send(token):
        if not token:
            raise remote.RemoteError("аккаунт ещё не входил — сначала вход")
        return remote.request("POST", path, timeout=timeout,
                              retry_busy=not protected,
                              json={"username": username, "state": token, **body})

    with _lock(username):
        generation = session_manager.state_generation(state_file(username))
        try:
            out = send(_state(username, generation)) if protected else _stale_retry(username, send, generation)
        except remote.RemoteError as exc:
            if not publication:
                if protected:
                    exc.stop_account = True
                    exc.network = False
                raise
            return _unknown_publication(str(exc))
        if publication:
            return _publication_out(username, out, generation)
        if upload:
            return _upload_out(username, path, body, out, generation)
        if not isinstance(out, dict):
            raise remote.RemoteError("сервер вернул ответ неверного формата")
        if not _save(username, out.pop("state", None), generation):
            raise remote.RemoteError("Состояние аккаунта изменено. Ответ не сохранён.", stop_account=True)
        return out


def _upload_out(username: str, path: str, body: dict, response, generation: int = None) -> dict:
    """Пропуск пригоден только вместе с полным ответом и сохранённым state."""
    def unconfirmed(message):
        return remote.RemoteError(message, stop_account=True, outcome_unknown=True)

    if not isinstance(response, dict):
        raise unconfirmed("Сервер не подтвердил подготовку загрузки. Проверьте результат перед повтором.")
    out = dict(response)
    token = out.pop("state", None)
    ticket = out.get("ticket")
    valid = isinstance(token, str) and bool(token.strip()) and out.get("state_saved") is not False
    valid = valid and isinstance(ticket, str) and bool(ticket.strip())

    def slot_valid(slot):
        return isinstance(slot, dict) and all(isinstance(slot.get(k), str) and slot[k].strip()
                                             for k in ("url", "auth", "user_id"))

    if path.rstrip("/").endswith("/photos/upload"):
        slots = out.get("slots")
        valid = valid and isinstance(slots, list) and len(slots) == len(body.get("sizes") or [])
        valid = valid and bool(slots) and all(slot_valid(slot) for slot in slots)
    elif path.rstrip("/").endswith("/videos/upload"):
        valid = valid and slot_valid(out.get("slot"))
        valid = valid and type(out.get("part_size")) is int and out["part_size"] > 0
    if not valid:
        raise unconfirmed("Сервер не подтвердил подготовку загрузки. Проверьте результат перед повтором.")
    try:
        if _write(state_file(username), token, generation) is False:
            raise unconfirmed("Состояние аккаунта изменено. Загрузка остановлена до отправки файлов.")
    except OSError:
        raise unconfirmed("Не удалось сохранить состояние после подготовки загрузки. Проверьте результат перед повтором.") from None
    return out


def _unknown_publication(message="") -> dict:
    return {"ok": False, "verdict": "unknown", "network": False,
            "retriable": False, "item_id": None, "stop_account": True,
            "message": message or "Результат публикации не подтверждён. Проверьте посты перед повтором."}


def _publication_out(username: str, response, generation: int = None) -> dict:
    """Сохранение состояния не отменяет подтверждённый результат поста."""
    if not isinstance(response, dict) or type(response.get("ok")) is not bool:
        return _unknown_publication()
    out = dict(response)
    item = out.get("item_id")
    item = str(item) if isinstance(item, (str, int)) and not isinstance(item, bool) else ""
    if out["ok"] and (out.get("verdict") != "ok" or not 1 <= len(item) <= 64
                      or not item.isascii() or not item.isdigit() or int(item) <= 0):
        out = {**out, **_unknown_publication()}
    token = out.pop("state", None)
    saved = isinstance(token, str) and bool(token.strip()) and out.get("state_saved") is not False
    if saved:
        try:
            saved = _write(state_file(username), token, generation) is not False
        except OSError:
            saved = False
    if not saved:
        out.update(state_saved=False, stop_account=True,
                   state_error="Не удалось сохранить новое состояние аккаунта. Не повторяйте пост; проверьте результат.")
    out.update(network=False, retriable=False)
    if out.get("verdict") in ("unknown", "risk_block"):
        out["stop_account"] = True
    if out["ok"]:
        out["item_id"] = item
    return out


def login(acc: dict, proxy: str) -> dict:
    """Вход с 2FA. {ok, reason, network, banned, ban_code}. Прежнее состояние
    уходит с запросом: сервер сохранит устройство и ключ Ticket Guard."""
    u = acc["username"]
    proxy = session_manager.sticky_proxy(proxy, u)
    body = {k: acc.get(k) or "" for k in
            ("username", "password", "totp_secret", "email", "email_password")}

    kept = session_manager.device_state_file(u)
    had_auth_state = False

    def send(token):
        nonlocal had_auth_state
        had_auth_state = bool(token and state_file(u).exists())
        # вход без строки — с компьютером, что остался от прошлого входа
        if not token and kept.exists():
            token = kept.read_text(encoding="utf-8").strip()
        return remote.request("POST", "/v1/login", timeout=LONG, retry_busy=False, json={
            **body, "proxy": proxy, "state": token or None})

    with _lock(u):
        auth_path = state_file(u)
        auth_generation = session_manager.state_generation(auth_path)
        kept_generation = session_manager.state_generation(kept)
        try:
            out = send(_state(u, auth_generation))
        except remote.RemoteError as exc:
            return {"ok": False, "reason": str(exc), "network": False,
                    "verdict": "unknown", "retriable": False, "state_saved": False}
        if not isinstance(out, dict) or type(out.get("ok")) is not bool:
            return {"ok": False, "reason": "Сервер не подтвердил вход", "network": False,
                    "verdict": "unknown", "retriable": False, "state_saved": False}
        out = dict(out)
        if out["ok"]:
            token = out.pop("state", None)
            saved = isinstance(token, str) and bool(token.strip()) and out.get("state_saved") is not False
            try:
                if saved:
                    saved = session_manager.complete_login_if_current(
                        auth_path, token, auth_generation, kept, kept_generation) is not False
            except OSError:
                saved = False
            if not saved:
                out.update(ok=False, reason="Не удалось сохранить подтверждённый вход аккаунта",
                           network=False, verdict="unknown", retriable=False, state_saved=False)
                return out
        else:
            saved = out.get("state")
            if isinstance(saved, str) and saved.strip():
                # Без прежнего входа состояние содержит только устройство,
                # не отмечаем его сессией. При 409 прежние файлы не стираются.
                target = auth_path if had_auth_state else kept
                generation = auth_generation if had_auth_state else kept_generation
                if _write(target, saved, generation) is False:
                    out.update(state_saved=False, network=False, retriable=False,
                               reason="Состояние аккаунта изменено. Поздний ответ входа не сохранён.")
        out.pop("state", None)
        return out


def keep_device(username: str) -> bool:
    """Перед «Забыть»/«Выйти»/«Удалить» без смены устройства: сервер вырезает
    из строки состояния куки, компьютер аккаунта остаётся в
    sessions/<имя>.device.state — следующий вход будет с ним. Прежняя сессия
    без строки сначала переносится на сервер (_state), чтобы и её компьютер
    не потерялся. False — компьютера нет. Если сервер не прочёл состояние
    или не ответил — RemoteError: стирать вход без сохранения устройства нельзя."""
    kept = session_manager.device_state_file(username)
    with _lock(username):
        auth_generation = session_manager.state_generation(state_file(username))
        kept_generation = session_manager.state_generation(kept)
        token = _state(username, auth_generation)
        if not token:
            if session_manager.has_session(username):
                raise remote.RemoteError("сервер не сохранил устройство — вход не стёрт")
            return kept.exists()
        out = remote.request("POST", "/v1/state/reset",
                             json={"username": username, "state": token})
        saved = out.get("state")
        if not isinstance(saved, str) or not saved.strip():
            raise remote.RemoteError("сервер не сохранил устройство — вход не стёрт")
        if _write(kept, saved, kept_generation) is False:
            raise remote.RemoteError("Состояние аккаунта изменено. Устройство не сохранено.", stop_account=True)
        return True


def _tos_session(proxy: str):
    """Чистая сессия к хранилищу TikTok через прокси аккаунта — без кук.
    Имя хранилища резолвит прокси (socks5h), как у остальных запросов: наш
    DNS подобрал бы узел под место компьютера, а не под выход прокси."""
    return requests.Session(impersonate=device.IMPERSONATE,
                            headers={"User-Agent": device.UA, **device.SEC_CH_UA},
                            proxies={"all": proxies.remote_dns(proxy)})


def upload_photos(username: str, proxy: str, blobs: list, sent: list = None) -> list:
    """Фото одного поста — в TikTok: пропуска сервера на все разом, байты
    через прокси аккаунта по порядку. Один запрос за пропусками — одна
    подготовка загрузки у TikTok на пост, как у страницы студии, а не на
    каждое фото. [{ticket, frame}] по порядку — для publish_photo_items;
    frame — превью для проверки поста (base64). sent — сюда номер фото
    кладётся перед его заливом: при сбое видно, какие могли дойти до TikTok.
    Сбой заливки — tos_upload.TOSUploadError, сервера — remote.RemoteError."""
    proxy = session_manager.sticky_proxy(proxy, username)
    up = _call(username, "/v1/photos/upload",
               {"proxy": proxy, "sizes": [len(b) for b in blobs]})
    s = _tos_session(proxy)
    out = []
    try:
        for index, (slot, data) in enumerate(zip(up["slots"], blobs)):
            if sent is not None:
                sent.append(index)
            tos_upload.put_photo(s, slot, data)
            out.append({"ticket": up["ticket"],
                        "frame": base64.b64encode(tos_upload.frame_jpeg(data)).decode()})
    finally:
        s.close()
    return out


def upload_photo(username: str, proxy: str, data: bytes) -> dict:
    """Одно фото — upload_photos из одного."""
    return upload_photos(username, proxy, [data])[0]


def publish_photo_items(username: str, proxy: str, items: list, caption: str = "",
                        title: str = "", cover_idx: int = 0, music: bool = True) -> dict:
    """Пост из фото, залитых upload_photos, по порядку. Ответ как у
    publish.publish_photo: {ok, verdict, code, message, item_id, network}."""
    # у фото одного вызова upload_photos билет общий: сервер берёт из него
    # все фото сразу, поэтому каждый билет — один раз
    tickets = list(dict.fromkeys(it["ticket"] for it in items))
    return _call(username, "/v1/photos/publish", {
        "proxy": proxy, "tickets": tickets,
        "frames": [it["frame"] for it in items], "caption": caption, "title": title,
        "cover_idx": cover_idx, "music": music})


def publish_photos(username: str, proxy: str, blobs: list, caption: str = "",
                   title: str = "", cover_idx: int = 0, music: bool = True) -> dict:
    """Фото-пост из байтов целиком: залить все и опубликовать."""
    items = upload_photos(username, proxy, blobs)
    return publish_photo_items(username, proxy, items, caption, title, cover_idx, music)


def upload_video(username: str, proxy: str, path) -> dict:
    """Видео — в TikTok частями с диска (целиком в память не читается).
    {ticket, crcs, meta} — для publish_video_item. Склейку делает сервер."""
    proxy = session_manager.sticky_proxy(proxy, username)
    path = Path(path)
    size = path.stat().st_size
    up = _call(username, "/v1/videos/upload", {"proxy": proxy, "size": size})
    step = up["part_size"]
    s = _tos_session(proxy)
    crcs = []
    try:
        with open(path, "rb") as f:
            for number, offset in enumerate(range(0, size, step), 1):
                f.seek(offset)
                crcs.append(tos_upload.put_part(s, up["slot"], number, offset,
                                                f.read(step)))
    finally:
        s.close()
    info = media_info.mp4_info(path) or {}
    return {"ticket": up["ticket"], "crcs": crcs,
            "meta": {k: info[k] for k in ("width", "height", "duration_ms", "has_audio")
                     if k in info}}


def publish_video_item(username: str, proxy: str, item: dict, caption: str = "") -> dict:
    """Пост из видео, залитого upload_video: склейка и публикация на сервере."""
    return _call(username, "/v1/videos/publish", {
        "proxy": proxy, "ticket": item["ticket"], "crcs": item["crcs"],
        "caption": caption, **item["meta"]})


def publish_video(username: str, proxy: str, path, caption: str = "") -> dict:
    """Видео-пост с диска целиком: залить и опубликовать."""
    return publish_video_item(username, proxy, upload_video(username, proxy, path), caption)


def delete_posts(username: str, proxy: str, count=None, item_ids: list = None) -> dict:
    """Удалить посты: count последних ("all" — все) или по списку item_ids.
    {deleted, failed, total} — как delete_post.delete_recent."""
    body = {"proxy": proxy}
    if item_ids:
        body["item_ids"] = [str(i) for i in item_ids]
    else:
        body["count"] = count if count is not None else "all"
    return _call(username, "/v1/posts/delete", body)


def studio(username: str, proxy: str, what: str, **extra) -> dict:
    """Студия аккаунта: what — posts, counters или profile."""
    if what not in ("posts", "counters", "profile"):
        raise ValueError(what)
    return _call(username, f"/v1/studio/{what}", {"proxy": proxy, **extra})["data"]












def session_check(username: str, proxy: str) -> dict:
    """Жива ли сессия: {alive, network?, stale?, error?} — как
    session_manager.check_alive. Не вошли вовсе — alive False без сети."""
    try:
        return _call(username, "/v1/session/check", {"proxy": proxy})["data"]
    except remote.RemoteError as exc:
        return {"alive": False, "network": exc.network, "error": str(exc)}


def notices(username: str, proxy: str) -> dict:
    """Уведомления аккаунта: {removed, items, more, error} — как
    publish.read_notices."""
    return _call(username, "/v1/notices", {"proxy": proxy})["data"]


def logout(username: str, proxy: str) -> dict:
    """Выход на стороне TikTok. Подтверждён — строка состояния больше не
    нужна и удаляется. {ok, confirmed, error}."""
    out = _call(username, "/v1/logout", {"proxy": proxy})
    if out.get("confirmed"):
        state_file(username).unlink(missing_ok=True)
    return out


def profiles(usernames: list, proxy: str, method: str = None, posts: bool = True,
             threads: int = 4) -> dict:
    """Любые профили без входа: {profiles, failed} — как profiles.fetch_remote."""
    return remote.request("POST", "/v1/profiles", timeout=LONG, json={
        "usernames": list(usernames), "proxy": proxy, "method": method,
        "posts": posts, "threads": threads})
