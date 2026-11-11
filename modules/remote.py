"""Nimbus service connection, account metadata and history."""
import ipaddress
import os
import threading
import time
import urllib.parse
from pathlib import Path

from curl_cffi import requests

from . import config

# Адрес нашего сервера по умолчанию — пока пользователь не задал свой в
# «Настройках». Для разработки — переменная окружения NIMBUS_SERVER
# (например http://127.0.0.1:8800), она главнее всего.
API_BASE = "https://78.153.139.65"
# корневой сертификат нашего сервера (server/tls/ca.pem с сервера)
SERVER_CA = Path(__file__).resolve().parent / "ca.pem"

ACCOUNT_PATH = "/v1/account"
HISTORY_PATH = "/v1/history"
# ответа ждём 20 с на само действие и ещё минуту на очередь сервера
# (server/limits.py WAIT_SECONDS): запрос стоит в ней, не переотправляясь
TIMEOUT = (10, 80)

# Ответ сервера человеческим текстом — для тоста и раздела «Профиль»
_STATUS_TEXT = {401: "ключ не подходит", 402: "на балансе нет средств",
                403: "ключ отключён", 503: "сервер перегружен"}


class RemoteError(RuntimeError):
    """Сервер не ответил или отказал; текст — для человека. network — до
    сервера не достучались или он сам не достучался до TikTok (502). Это
    диагностика, не разрешение повторить действие. status — HTTP-код ответа,
    0 — ответа не было."""

    def __init__(self, text: str, status: int = 0, network: bool = False, *,
                 stop_account: bool = False, outcome_unknown: bool = False):
        super().__init__(text)
        self.status = status
        self.network = network
        self.stop_account = stop_account
        self.outcome_unknown = outcome_unknown


def base() -> str:
    return (os.environ.get("NIMBUS_SERVER") or config.get("server_url")
            or API_BASE).rstrip("/")


def normalize_server(text: str) -> str:
    """Что ввёл пользователь -> https://хост[:порт]. «1.2.3.4», «1.2.3.4:1337»,
    «https://nimbus.example.com» — всё годится; путь и мусор — ValueError."""
    text = (text or "").strip().rstrip("/")
    if "://" not in text:
        text = "https://" + text
    u = urllib.parse.urlsplit(text)
    if u.scheme not in ("http", "https") or not u.hostname or u.path or u.query:
        raise ValueError("неверный адрес")
    try:
        u.port  # noqa: B018 — бросит на кривом порте
    except ValueError as exc:
        raise ValueError("неверный адрес") from exc
    return f"{u.scheme}://{u.netloc}"


def _verify(url: str):
    """По IP — только наш корневой сертификат, по домену — обычные."""
    try:
        ipaddress.ip_address(urllib.parse.urlsplit(url).hostname or "")
    except ValueError:
        return True
    return str(SERVER_CA) if SERVER_CA.exists() else True


# через сколько прокси пробовать дойти до сервера, если напрямую не пустили:
# у каждого по CHECK_TRIES узлов, дальше ждать уже дольше, чем стоит
ROUTE_MAX = 3
# напрямую не пустили — столько секунд сразу идём через прокси, потом снова
# пробуем напрямую (провайдер мог передумать, VPN включили)
DIRECT_RETRY_SEC = 300
# живой сервер отвечает на соединение за доли секунды: дольше — провайдер
# режет, и ждать его отказа все 10 с незачем
DIRECT_CONNECT = 3
_direct_off_until = 0.0
_local = threading.local()
_profile_negotiated = {}
_profile_lock = threading.Lock()


def _ensure_browser_profile(url: str, profile: str, token: str, proxy: str | None = None) -> None:
    """Проверка до действия: старый сервер не должен выполнить его под Chrome."""
    cache_key = (url, profile)
    with _profile_lock:
        if _profile_negotiated.get(cache_key, 0) > time.monotonic():
            return
    response = _send("GET", url + "/v2/health", proxy=proxy, timeout=TIMEOUT, verify=_verify(url),
                     headers={"Authorization": f"Bearer {token}",
                              "X-TikTok-Browser-Profile": profile})
    if response.status_code != 200 or response.headers.get("X-TikTok-Browser-Profile") != profile:
        raise RemoteError("сервер не поддерживает выбранный профиль браузера")
    with _profile_lock:
        _profile_negotiated[cache_key] = time.monotonic() + 60


# ошибки curl, при которых запрос до сервера точно не дошёл: не нашли адрес,
# не соединились, прокси отказал, TLS не сложился. Только их можно повторить
# другим путём — оборвалось после отправки, и действие (пост!) сервер мог уже
# выполнить: повтор выполнил бы его дважды
_UNSENT_CODES = {5, 6, 7, 35, 60, 97}


def _unsent(exc: Exception) -> bool:
    code = getattr(exc, "code", None)
    code = getattr(code, "value", code)
    if code in _UNSENT_CODES:
        return True
    # 28 — и таймаут соединения, и таймаут ответа; повторять можно только первый
    return code == 28 and "Connection timed out" in str(exc)


def _session(route: str):
    """Сессия этого потока к серверу по маршруту ("" — напрямую): держит
    соединение между запросами. У каждого потока своя — curl_cffi.Session
    одним потоком за раз."""
    pool = getattr(_local, "sessions", None)
    if pool is None:
        pool = _local.sessions = {}
    s = pool.get(route)
    if s is None:
        s = pool[route] = requests.Session()
        if route:
            s.proxies = {"all": route}
    return s


def _routes(proxy: str | None = None) -> list:
    """Через какие прокси идти к серверу, если напрямую не пустили: сначала
    прокси аккаунта, за ним живые из списка — до ROUTE_MAX. Пусто — прокси
    выключены, списка нет или живых нет."""
    from . import proxies, proxy_pool
    try:
        alive = proxy_pool._alive_now(recheck=False)[1]
    except Exception:  # noqa: BLE001 — пул не ответил: только прокси аккаунта
        alive = []
    out = []
    for p in ([proxy] if proxy else []) + list(alive):
        p = proxies.remote_dns(p)
        if p and p not in out:
            out.append(p)
    return out[:ROUTE_MAX]


def _send(method: str, url: str, proxy: str | None = None, **kw):
    """Запрос к серверу: сначала напрямую, не достучались — через прокси
    (см. _routes). Сбой и там — исключение последней попытки. Другим путём
    повторяется только запрос, который точно не ушёл (_unsent).

    На каждый прокси — CHECK_TRIES попыток, как у проверки прокси:
    ротационный прокси берёт новый узел на каждое соединение, и узел, который
    до сервера не дошёл (или подменил сертификат — корпоративный фильтр),
    не приговор прокси. Ждать соединения через прокси — сколько везде ждёт
    пул: резидентный прокси соединяется секундами."""
    global _direct_off_until
    failed = None
    direct = time.monotonic() >= _direct_off_until
    timeout = kw.get("timeout")
    if direct:
        direct_kw = dict(kw)
        if isinstance(timeout, tuple):
            direct_kw["timeout"] = (min(timeout[0], DIRECT_CONNECT), timeout[1])
        try:
            return _session("").request(method, url, **direct_kw)
        except Exception as exc:  # noqa: BLE001 — напрямую не пустили: через прокси
            if not _unsent(exc):
                raise
            failed = exc
            # не ждать тот же отказ на каждом запросе: какое-то время сразу прокси
            _direct_off_until = time.monotonic() + DIRECT_RETRY_SEC
    from . import proxy_pool
    via_kw = dict(kw)
    if isinstance(timeout, tuple):
        via_kw["timeout"] = (max(timeout[0], proxy_pool.CONNECT_TIMEOUT), timeout[1])
    for via in _routes(proxy):
        for _ in range(proxy_pool.CHECK_TRIES):
            try:
                return _session(via).request(method, url, **via_kw)
            except Exception as exc:  # noqa: BLE001 — узел не довёл: следующий
                if not _unsent(exc):
                    raise
                failed = exc
    if not direct:
        # прокси не довели, а напрямую в этот раз не пробовали — последний шанс
        return _session("").request(method, url, **kw)
    raise failed


def ping(url: str = None) -> dict:
    """Доступен ли наш сервер: GET /v1/health. {ok, ms} или {ok: False,
    error} — текст для человека. Никогда не бросает: это статус, не отказ."""
    url = url or base()
    t0 = time.monotonic()
    try:
        r = _send("GET", url + "/v1/health", timeout=(5, 10), verify=_verify(url))
        ok = r.status_code == 200 and bool(r.json().get("ok"))
    except Exception as exc:  # noqa: BLE001
        # сертификат не наш — значит, и сервер не наш: для человека это одно
        name = type(exc).__name__
        why = ("не наш сервер" if "Certificate" in name or "SSL" in name
               else "не отвечает")
        return {"ok": False, "error": why}
    if not ok:
        return {"ok": False, "error": "не наш сервер"}
    return {"ok": True, "ms": round((time.monotonic() - t0) * 1000)}


def set_server(text: str) -> str:
    """Свой адрес сервера — сохранить как ввели (доступность смотрит ping
    отдельно). Пусто — встроенный. Кривой адрес — RemoteError, не пишем.
    Возвращает адрес, по которому теперь ходим."""
    if not (text or "").strip():
        config.update({"server_url": ""})
        return base()
    try:
        url = normalize_server(text)
    except ValueError as exc:
        raise RemoteError(str(exc)) from exc
    config.update({"server_url": url})
    return url


def key() -> str:
    return (config.get("license_key") or "").strip()


def _protected(method: str, path: str) -> bool:
    """Вход, загрузка, публикация, удаление и выход отправляются без повтора."""
    return method.upper() == "POST" and (path.rstrip("/") in ("/v1/login", "/v2/login")
                                        or path.rstrip("/").endswith(("/publish", "/upload", "/posts/delete", "/logout")))


def request(method: str, path: str, params: dict = None, json: dict = None,
            api_key: str = None, timeout=TIMEOUT, *, retry_busy: bool = True) -> dict:
    """Запрос к нашему серверу -> JSON ответа. Отказ — RemoteError с текстом
    сервера (он пишет его для человека в detail). Запрос аккаунта (в теле
    есть proxy) идёт к серверу через прокси этого аккаунта. retry_busy=False
    отключает повтор 503 для действий, чей исход нельзя угадывать."""
    from . import client_device
    protected = _protected(method, path)
    retry_busy = retry_busy and not protected
    browser_profile = client_device.browser_profile()
    profile_action = not (method.upper() == "GET" and path.rstrip("/") in
                          ("/v1/health", ACCOUNT_PATH, HISTORY_PATH))
    token = api_key if api_key is not None else key()
    if not token:
        raise RemoteError("ключ не задан")
    proxy = json.get("proxy") if isinstance(json, dict) else None
    if (isinstance(proxy, str) and proxy
            and not any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in proxy)):
        try:
            endpoint = urllib.parse.urlsplit(proxy if "://" in proxy else "//" + proxy)
            if (endpoint.scheme not in ("", "http", "https", "socks4", "socks4a", "socks5", "socks5h")
                    or not endpoint.hostname or endpoint.port == 0
                    or endpoint.path not in ("", "/") or endpoint.query or endpoint.fragment):
                proxy = None
        except ValueError:
            proxy = None
    else:
        proxy = None
    # Без отдельного подтверждения 503 не доказывает, что защищённое действие
    # не началось. Для остальных запросов ожидание задаёт server_wait_min.
    deadline = time.monotonic() + config.server_wait_min() * 60
    while True:
        try:
            url = base()
            if browser_profile == "firefox155" and profile_action:
                _ensure_browser_profile(url, browser_profile, token, proxy=proxy)
            wire_path = "/v2/" + path[len("/v1/"):] if profile_action and browser_profile == "firefox155" and path.startswith("/v1/") else path
            r = _send(method, url + wire_path, proxy=proxy,
                      params=params or {}, json=json, timeout=timeout, verify=_verify(url),
                      **({"allow_redirects": False} if protected else {}),
                      headers={"Authorization": f"Bearer {token}",
                               "Accept": "application/json",
                               "X-TikTok-Browser-Profile": browser_profile})
        except RemoteError as exc:
            if protected:
                exc.stop_account = True
                exc.network = False
            raise
        except Exception as exc:  # noqa: BLE001
            raise RemoteError(f"сервер не отвечает ({type(exc).__name__})",
                              network=not protected, stop_account=protected,
                              outcome_unknown=protected) from exc
        if r.status_code != 503 or not retry_busy or time.monotonic() >= deadline:
            break
        try:
            pause = max(1, min(int(r.headers.get("Retry-After") or 3), 30))
        except ValueError:
            pause = 3
        time.sleep(pause)
    if r.status_code in _STATUS_TEXT:
        raise RemoteError(_STATUS_TEXT[r.status_code], r.status_code,
                          stop_account=protected,
                          outcome_unknown=protected and r.status_code >= 500)
    try:
        out = r.json()
    except ValueError as exc:
        raise RemoteError(f"сервер ответил HTTP {r.status_code} не JSON",
                          r.status_code, r.status_code >= 500 and not protected,
                          stop_account=protected, outcome_unknown=protected) from exc
    if r.status_code != 200:
        detail = out.get("detail") if isinstance(out, dict) else None
        raise RemoteError(detail if isinstance(detail, str)
                          else f"сервер ответил HTTP {r.status_code}",
                          r.status_code, r.status_code >= 500 and not protected,
                          stop_account=protected,
                          outcome_unknown=protected and r.status_code >= 500)
    if profile_action and browser_profile == "firefox155" and r.headers.get("X-TikTok-Browser-Profile") != browser_profile:
        raise RemoteError("сервер не подтвердил профиль браузера", r.status_code,
                          stop_account=protected, outcome_unknown=protected)
    return out


def _get(path: str, params: dict = None, api_key: str = None) -> dict:
    return request("GET", path, params=params, api_key=api_key)


def _masked(token: str) -> str:
    return f"…{token[-4:]}" if len(token) > 4 else ""


def _owner_avatar_url(value) -> str | None:
    """The billing service returns either an HTTPS image or its public avatar path."""
    if not isinstance(value, str) or any(ord(c) < 32 for c in value):
        return None
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme == "https" and parsed.hostname and not parsed.username:
        return value
    if (not parsed.scheme and not parsed.netloc and not parsed.query and not parsed.fragment
            and value.startswith("/avatar/") and value[8:].isascii() and value[8:].isdigit()):
        return "https://muted.top" + value
    return None


_owner_avatar_cache = {}
_owner_avatar_lock = threading.Lock()


def owner_avatar() -> tuple[bytes, str]:
    """Fetch the current owner's image once; never send the API key to the image host."""
    identity = key()
    with _owner_avatar_lock:
        hit = _owner_avatar_cache.get(identity)
        if hit and time.monotonic() - hit[0] < 3600:
            return hit[1], hit[2]
        url = _owner_avatar_url(_get(ACCOUNT_PATH).get("avatar_url"))
        if not url:
            raise RemoteError("Аватар отсутствует", 404)
        routes = _routes()
        for route in routes[:1] + [None]:
            try:
                response = requests.get(url, proxy=route, timeout=(8, 12),
                                        allow_redirects=False)
                ctype = response.headers.get("Content-Type", "").split(";", 1)[0]
                if (response.status_code != 200 or ctype not in
                        ("image/jpeg", "image/png", "image/webp", "image/gif")
                        or not 0 < len(response.content) <= 512 * 1024):
                    continue
                _owner_avatar_cache.clear()
                _owner_avatar_cache[identity] = (time.monotonic(), response.content, ctype)
                return response.content, ctype
            except Exception:  # image failure leaves the visible fallback available
                continue
    raise RemoteError("Аватар не загрузился", 404)


def account(api_key: str = None) -> dict:
    """Состояние ключа: {key, status, balance, currency, name, expires_at}."""
    data = _get(ACCOUNT_PATH, api_key=api_key)
    return {"key": _masked(api_key if api_key is not None else key()),
            "status": data.get("status") or "active",
            "balance": data.get("balance"),
            "currency": data.get("currency") or "",
            "name": data.get("name") or "",
            "avatar_url": ("api/license/avatar?v=" + urllib.parse.quote(_masked(api_key if api_key is not None else key()))
                           if _owner_avatar_url(data.get("avatar_url")) else None),
            "expires_at": data.get("expires_at")}


def history(limit: int = 50, cursor: str = None) -> dict:
    """Списания по ключу: {items: [...], next}."""
    params = {"limit": max(1, min(int(limit or 50), 200))}
    if cursor:
        params["cursor"] = cursor
    data = _get(HISTORY_PATH, params)
    items = [{"at": it.get("at"), "action": it.get("action") or "",
              "title": it.get("title") or it.get("action") or "",
              "account": it.get("account") or "", "note": it.get("note") or "",
              "kind": "credit" if it.get("kind") == "credit" else "debit",
              "amount": it.get("amount"),
              "ok": bool(it.get("ok", True)), "error": it.get("error") or ""}
             for it in (data.get("items") or []) if isinstance(it, dict)]
    return {"items": items, "next": data.get("next")}


def set_key(new_key: str) -> dict:
    """Проверить ключ у сервера и сохранить; не подошёл — RemoteError, старый
    ключ остаётся. Пустой ключ — удалить."""
    new_key = (new_key or "").strip()
    if not new_key:
        config.update({"license_key": ""})
        return {"key": "", "status": "none"}
    info = account(new_key)
    config.update({"license_key": new_key})
    return info


def status() -> dict:
    """Для раздела «Профиль»: состояние ключа или причина, почему его нет."""
    if not key():
        return {"key": "", "status": "none"}
    try:
        return account()
    except RemoteError as exc:
        return {"key": _masked(key()), "status": "error", "error": str(exc)}
