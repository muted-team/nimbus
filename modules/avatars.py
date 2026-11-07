"""Local image cache for account avatars returned by the Nimbus service."""
# -*- coding: utf-8 -*-
import base64
import sqlite3
import time
import urllib.parse
import io
import hashlib
import warnings
from contextlib import closing

from . import db

# картинка больше этого — не аватарка (или CDN отдал что-то не то)
_MAX_BYTES = 512 * 1024




def _mime_of(raw: bytes, content_type: str) -> str:
    """MIME по сигнатуре файла; заголовок — только запасной вариант."""
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    if raw[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    ct = (content_type or "").split(";")[0].strip().lower()
    return ct if ct.startswith("image/") else ""


def store(username: str, raw: bytes, content_type: str = "", src: str = "") -> bool:
    """Кладёт картинку аккаунта в базу (перезаписывает прежнюю). src — с
    какой картинки скачана (source_of); пусто — неизвестно."""
    if not username or not raw or len(raw) > _MAX_BYTES:
        return False
    mime = _mime_of(raw, content_type)
    if not mime:
        return False
    data = "data:%s;base64,%s" % (mime, base64.b64encode(raw).decode("ascii"))
    with closing(db.connect()) as conn:
        conn.execute(
            "INSERT INTO avatars (username, data, updated_at, src) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(username) DO UPDATE SET"
            " data = excluded.data, updated_at = excluded.updated_at, src = excluded.src",
            (username, data, int(time.time()), src or None))
        conn.commit()
    return True


def source_of(url: str) -> str:
    """Постоянная часть ссылки на аватарку — путь: в нём id картинки, а query
    (x-expires, x-signature) меняется на каждый запрос профиля."""
    return urllib.parse.urlsplit(url or "").path


def stored_source(username: str) -> str:
    """src сохранённой аватарки; нет картинки или src — пусто."""
    try:
        with closing(db.connect()) as conn:
            row = conn.execute("SELECT src FROM avatars WHERE username = ?",
                               (username,)).fetchone()
    except sqlite3.Error:
        return ""
    return (row and row[0]) or ""


def fetch_and_store(session, url: str, username: str, prof: dict) -> bool:
    """Скачивает аватарку сессией входа и сохраняет. Ничего не кидает."""
    if not url:
        print("[avatar] в ответе входа нет avatar_url")
        return False
    try:
        r = session.get(url, timeout=20, headers={
            "User-Agent": prof["ua"],
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Referer": "https://www.tiktok.com/",
        })
        if r.status_code != 200:
            print(f"[avatar] HTTP {r.status_code} — аватарка не сохранена")
            return False
        ok = store(username, r.content, r.headers.get("Content-Type", ""))
        print("[avatar] сохранена" if ok else "[avatar] ответ не похож на картинку")
        return ok
    except Exception as exc:  # noqa: BLE001 — аватарка не должна ронять вход
        print(f"[avatar] не сохранена: {type(exc).__name__}: {exc}")
        return False


def versions() -> dict:
    """{username: updated_at} — лёгкий запрос для опроса списка аккаунтов."""
    try:
        with closing(db.connect()) as conn:
            return dict(conn.execute("SELECT username, updated_at FROM avatars"))
    except sqlite3.Error:
        return {}


def all_data() -> dict:
    """{username: data URI} — все картинки разом (GET /api/avatars)."""
    try:
        with closing(db.connect()) as conn:
            return dict(conn.execute("SELECT username, data FROM avatars"))
    except sqlite3.Error:
        return {}


def data_of(usernames: list) -> dict:
    """{username: {"data": data URI, "at": updated_at}} только для usernames —
    свежие аватарки в живой поток UI, не гоняя все картинки разом."""
    out = {}
    if not usernames:
        return out
    try:
        with closing(db.connect()) as conn:
            for i in range(0, len(usernames), 500):  # потолок переменных SQLite
                part = usernames[i:i + 500]
                for name, data, at in conn.execute(
                        "SELECT username, data, updated_at FROM avatars"
                        f" WHERE username IN ({', '.join('?' * len(part))})", part):
                    out[name] = {"data": data, "at": at}
    except sqlite3.Error:
        pass
    return out


def remove(username: str) -> None:
    """Удаляет аватарку, профиль и посты аккаунта (вместе с аккаунтом)."""
    try:
        with closing(db.connect()) as conn:
            conn.execute("DELETE FROM avatars WHERE username = ?", (username,))
            conn.execute("DELETE FROM profiles WHERE username = ?", (username,))
            conn.execute("DELETE FROM posts WHERE username = ?", (username,))
            conn.commit()
    except sqlite3.Error:
        pass


def rename(old: str, new: str) -> None:
    """Переносит аватарку, профиль и посты со старого username на новый

    (ручное исправление логина в accounts.py:update_account). Если под новым
    именем уже случайно остались строки от давно удалённого аккаунта — они
    сносятся первыми, иначе перенос упёрся бы в PRIMARY KEY. Сбой — не
    критичная ошибка: сама запись в accounts.json уже переименована,
    просто старые числа найдутся не сразу, а после следующего обновления
    профиля."""
    if not old or not new or old == new:
        return
    try:
        with closing(db.connect()) as conn:
            conn.execute("DELETE FROM avatars WHERE username = ?", (new,))
            conn.execute("DELETE FROM profiles WHERE username = ?", (new,))
            conn.execute("DELETE FROM posts WHERE username = ?", (new,))
            conn.execute("UPDATE avatars SET username = ? WHERE username = ?", (new, old))
            conn.execute("UPDATE profiles SET username = ? WHERE username = ?", (new, old))
            conn.execute("UPDATE posts SET username = ? WHERE username = ?", (new, old))
            conn.commit()
    except sqlite3.Error as exc:
        print(f"[avatar] перенос {old} -> {new} не вышел: {type(exc).__name__}: {exc}")
