# -*- coding: utf-8 -*-
"""Понятные причины неудач — для ленты «Логи», тостов и итогов кампании.

Модули разбирают ответы TikTok языком разработчика: «risk_block», «HTTP 403 +
anti-bot код 40001», «tt-ticket-guard-result=1004», «curl: (56) CONNECT
tunnel failed, response 407». Пользователю нужна одна строка: что случилось и
что с этим делать. Техника остаётся в подробностях журнала (обычный print).

Тексты начинаются со строчной буквы: их вклеивают после «вход не удался: »,
«пост №2 не опубликован: », а заглавную первую букву в ленте ставит UI.
"""
import re

CAPTCHA = "капча"
SESSION_EXPIRED = "сессия протухла"
NETWORK = "сбой сети"
# Прокси жив, но дальше не пускает — повторять тот же запрос бесполезно
PROXY_AUTH = "прокси не принял логин или пароль"
PROXY_NO_EXIT = "у прокси нет выхода — страна не поддерживается или узел недоступен"
PROXY_PLAN = "прокси отказал — тариф истёк или прокси на паузе у провайдера"
PROXY_REFUSED = (PROXY_AUTH, PROXY_NO_EXIT, PROXY_PLAN)

# код ошибки libcurl из текста исключения curl_cffi: «curl: (28) …»
_CURL_CODE_RE = re.compile(r"curl: \((\d+)\)")
# ответ прокси, который дальше не пустил: «CONNECT tunnel failed, response
# 502» у http и «cannot complete SOCKS5 connection to host. (4)» у SOCKS5
_PROXY_REPLY_RE = re.compile(
    r"tunnel failed, response (403|50[23])|cannot complete socks5 connection[^(]*\(([24])\)")


def network(exc) -> str:
    """Сетевое исключение (curl_cffi) или его текст -> короткая причина."""
    text = str(exc)
    low = text.lower()
    m = _CURL_CODE_RE.search(text)
    code = int(m.group(1)) if m else None
    if (("407" in low and ("proxy" in low or "tunnel" in low or code == 56))
            or "rejected by the socks5 server" in low):
        return PROXY_AUTH
    # Ответ самого прокси на CONNECT (http) или код отказа SOCKS5 (RFC 1928):
    # прокси жив, но дальше не пустил. Тексты сняты с noshadow 17.10.2026
    # (dev/NOSHADOW.md): 502/503 и SOCKS «(4)» — выхода в эту страну нет,
    # 403 и SOCKS «(2)» — тариф истёк или прокси на паузе.
    reply = _PROXY_REPLY_RE.search(low)
    if reply:
        if (reply.group(1) or reply.group(2)) in ("403", "2"):
            return PROXY_PLAN
        return PROXY_NO_EXIT
    # сначала код libcurl — он точный; в тексте «SSL_connect» и «connect to
    # proxy» слова перекрываются, по ним — только когда кода нет
    by_code = {
        28: "прокси или сеть не ответили вовремя",
        5: "прокси не отвечает — проверьте адрес и порт",
        97: "прокси не отвечает — проверьте адрес и порт",
        6: "адрес не найден — нет интернета или прокси указан неверно",
        7: "не удалось подключиться — прокси или сеть недоступны",
        35: "соединение оборвалось — прокси или сеть",
        52: "соединение оборвалось — прокси или сеть",
        55: "соединение оборвалось — прокси или сеть",
        56: "соединение оборвалось — прокси или сеть",
    }
    if code in by_code:
        return by_code[code]
    if "timed out" in low or "timeout" in low:
        return by_code[28]
    if "proxy" in low or "socks" in low or "tunnel" in low:
        return by_code[5]
    if "resolve" in low:
        return by_code[6]
    if "ssl" in low or "reset" in low:
        return by_code[35]
    if "connect" in low:
        return by_code[7]
    return NETWORK


def is_network(exc) -> bool:
    """Исключение сетевого уровня: curl_cffi, таймаут, отказ соединения."""
    module = type(exc).__module__ or ""
    return (module.startswith("curl_cffi")
            or isinstance(exc, (TimeoutError, ConnectionError)))


def error(exc) -> str:
    """Любое исключение -> короткая причина.

    Сеть — через network(). Свои ошибки модулей (ValueError, RuntimeError и
    их наследники вроде ProfileError) пишутся по-русски сразу для человека —
    их текст идёт как есть. Всё прочее — сбой внутри программы: имя класса
    без трассировки, сама трассировка остаётся в подробностях."""
    if is_network(exc):
        return network(exc)
    text = str(exc).strip()
    if isinstance(exc, (ValueError, RuntimeError, FileNotFoundError)) and text:
        return text
    return "внутренняя ошибка программы (%s)" % type(exc).__name__


def verdict(v: dict) -> str:
    """Вердикт publish.classify_publish_response (или результат publish_photo)
    -> короткая причина."""
    kind = v.get("verdict")
    message = (v.get("message") or "").strip()
    code = v.get("code")
    if kind == "risk_block":
        return CAPTCHA
    if kind == "auth":
        return SESSION_EXPIRED
    if kind == "ticket":
        return "TikTok отклонил подпись запроса"
    if kind == "transient":
        if message.startswith("HTTP "):
            return "TikTok временно недоступен (%s)" % message
        if "curl" in message.lower():
            return network(message)
        return NETWORK
    if kind == "biz_error":
        # status_msg TikTok — его собственный человеческий текст; без него
        # остаётся только код
        if message and message != "частичный сбой поста":
            return "TikTok отклонил пост: %s" % message
        return "TikTok отклонил пост (код %s)" % code if code else "TikTok отклонил пост"
    return message or "неизвестная ошибка"
