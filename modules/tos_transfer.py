# -*- coding: utf-8 -*-
"""Передача байтов на TOS по слоту, выданному сервером.

Модуль не получает токены и не создаёт слоты: клиенту достаточно url, auth и
user_id из ответа сервера, чтобы отправить фото или части видео.
"""
import io
import json
import time
import zlib

from curl_cffi import requests

from . import client_device as device
from .proxy_pool import CONNECT_TIMEOUT


class TOSUploadError(RuntimeError):
    """Ошибка передачи байтов в TOS или ответа TOS."""

    def __init__(self, message, *, stop_account=False, outcome_unknown=False):
        super().__init__(message)
        self.stop_account = stop_account
        self.outcome_unknown = outcome_unknown


_NET_ATTEMPTS = 3
_NET_BACKOFF = (2.0, 5.0)


def _net(fn, *, retry_safe=False):
    """Запись отправляется один раз; повтор разрешён только для чтения."""
    last = None
    attempts = _NET_ATTEMPTS if retry_safe else 1
    for attempt in range(attempts):
        try:
            return fn()
        except device.CorsError as exc:
            raise TOSUploadError("TikTok не разрешил загрузку или требует проверки.",
                                 stop_account=True) from exc
        except requests.RequestsError as exc:
            last = exc
            if attempt < attempts - 1:
                pause = _NET_BACKOFF[min(attempt, len(_NET_BACKOFF) - 1)]
                print(f"[tos] сетевой сбой ({type(exc).__name__}), "
                      f"повтор чтения {attempt + 2}/{attempts} через {pause:.0f} с")
                time.sleep(pause)
    raise TOSUploadError("Ответ загрузки не получен. Проверьте результат перед повтором.",
                         stop_account=True, outcome_unknown=not retry_safe) from last


def upload_response(resp, what: str, *, restrictions_only=False) -> None:
    """Явный отказ и HTTP-ошибка не разрешают следующий шаг загрузки."""
    headers = {name.lower(): value for name, value in resp.headers.items()}
    blocked = resp.status_code in (403, 429) or any(
        name in headers for name in ("bdturing-verify", "x-tt-verify-idv-decision-conf"))
    try:
        body = resp.json()
    except (ValueError, TypeError):
        body = {}
    if isinstance(body, dict):
        containers = [body]
        if isinstance(body.get("data"), dict):
            containers.append(body["data"])
        message = " ".join(str(container.get(name) or "") for container in containers
                           for name in ("status_msg", "msg", "message", "description")).lower()
        blocked = blocked or any(fragment in message for fragment in
                                 ("too many", "maximum number", "attempts reached",
                                  "rate limit", "captcha", "challenge"))
    if blocked:
        raise TOSUploadError("TikTok ограничил загрузку или требует проверки.",
                             stop_account=True)
    if not restrictions_only and not 200 <= resp.status_code < 300:
        raise TOSUploadError(f"{what}: HTTP {resp.status_code} — загрузка не подтверждена.",
                             stop_account=True, outcome_unknown=resp.status_code >= 500)


def terminal_upload_error(exc) -> bool:
    """Необязательная подготовка также останавливается на защищённом отказе."""
    return (getattr(exc, "stop_account", False) or
            isinstance(exc, device.CorsError))


def put_photo(session, slot: dict, data: bytes) -> str:
    """Отправляет фото на TOS по слоту и возвращает CRC32 файла."""
    crc = format(zlib.crc32(data) & 0xffffffff, "08x")
    resp = _net(lambda: device.cors_post(session, slot["url"], site="cross-site", headers={
        **device.fetch_headers("cross-site"),
        "Origin": "https://www.tiktok.com",
        "Authorization": slot["auth"],
        "X-Storage-U": slot["user_id"],
        "Content-CRC32": crc,
        "Content-Type": "application/octet-stream",
        "Content-Disposition": 'attachment; filename="undefined"',
        "Referer": "https://www.tiktok.com/",
    }, data=data, timeout=(CONNECT_TIMEOUT, 180), allow_redirects=False))
    result = tos_json(resp, "фото")
    if result.get("code") != 2000:
        raise TOSUploadError("TOS не подтвердил загрузку фото.", stop_account=True)
    got = result.get("data")
    if got is not None and not isinstance(got, dict):
        raise TOSUploadError("Фото: неверный формат подтверждения загрузки.",
                             stop_account=True, outcome_unknown=True)
    got = (got or {}).get("crc32")
    if got and got != crc:
        raise TOSUploadError("Фото: CRC32 ответа не совпал с файлом.", stop_account=True)
    return crc


def tos_json(resp, what: str) -> dict:
    upload_response(resp, what)
    try:
        out = resp.json()
    except ValueError:
        raise TOSUploadError(f"{what}: ответ не JSON — результат не подтверждён.",
                             stop_account=True, outcome_unknown=True)
    if not isinstance(out, dict):
        raise TOSUploadError(f"{what}: ответ не объект — результат не подтверждён.",
                             stop_account=True, outcome_unknown=True)
    return out


PART_SIZE = 3 * 1024 * 1024


def tos_headers(slot: dict, user_agent: str = None) -> dict:
    """Заголовки передачи части видео."""
    ua = {"User-Agent": user_agent} if user_agent else {}
    return {**ua, **device.fetch_headers("cross-site"),
            "Referer": "https://www.tiktok.com/",
            "Origin": "https://www.tiktok.com", "X-Storage-U": slot["user_id"],
            "X-Enable-Upload-Mode": "stream", "Authorization": slot["auth"]}


def parts(size: int):
    """Номера, смещения и длины частей видео."""
    return [(n, off, min(PART_SIZE, size - off))
            for n, off in enumerate(range(0, size, PART_SIZE), 1)]


def put_part(session, slot: dict, number: int, offset: int, chunk: bytes,
             user_agent: str = None) -> str:
    """Отправляет одну часть видео по слоту и возвращает её CRC32."""
    crc = format(zlib.crc32(chunk) & 0xffffffff, "08x")
    headers = {**tos_headers(slot, user_agent),
               "Content-Type": "application/octet-stream",
               "Content-CRC32": "Ignore",
               "X-Part-Number": str(number),
               "X-Part-Offset": str(offset),
               "X-Enable-Omit-Init-Upload": "1",
               "X-Size": str(len(chunk)),
               "X-Offset": "0",
               "X-Phase": "transfer",
               "Content-Disposition": 'attachment; filename="undefined"'}
    resp = _net(lambda: device.cors_post(session, slot["url"], headers, "cross-site",
                                         data=chunk, timeout=(CONNECT_TIMEOUT, 180),
                                         allow_redirects=False))
    part = tos_json(resp, f"часть {number}")
    if part.get("code") != 2000:
        raise TOSUploadError(f"Часть {number}: TOS не подтвердил загрузку.", stop_account=True)
    data = part.get("data")
    got = data.get("crc32") if isinstance(data, dict) else None
    if got != crc:
        raise TOSUploadError(f"Часть {number}: подтверждение CRC32 отсутствует или не совпало.",
                             stop_account=True, outcome_unknown=True)
    return crc


FRAME_SIDE = 256
FRAME_QUALITY = 80


def frame_jpeg(data: bytes) -> bytes:
    """Уменьшает фото до превью для tiktok-ai-frame."""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:  # noqa: BLE001 — без превью пост всё равно уйдёт
        return b""
    scale = FRAME_SIDE / max(im.size)
    im = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))),
                   Image.BILINEAR)
    out = io.BytesIO()
    im.save(out, "JPEG", quality=FRAME_QUALITY)
    return out.getvalue()
