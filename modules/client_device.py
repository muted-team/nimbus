"""Browser transport profiles used by the client."""

import contextlib
import contextvars
import os
import time
from urllib.parse import urlsplit

from . import config

CHROME_VERSION = "152"
FIREFOX_VERSION = "155"
_CHROME_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")
_FIREFOX_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:155.0) "
               "Gecko/20100101 Firefox/155.0")
_SPECS = {
    "chrome152": {"UA": _CHROME_UA, "APP_VERSION": _CHROME_UA[len("Mozilla/"):],
                  "IS_FIREFOX": False, "SEC_CH_UA": {
                      "sec-ch-ua": '\"Not?A_Brand\";v=\"24\", \"Chromium\";v=\"152\"',
                      "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '\"Windows\"'}},
    "firefox155": {"UA": _FIREFOX_UA, "APP_VERSION": "5.0 (Windows)",
                   "IS_FIREFOX": True, "SEC_CH_UA": {}},
}
BROWSER_PROFILES = tuple(_SPECS)
_browser = contextvars.ContextVar("tiktok_browser_profile", default=None)
_DEFAULT_PROFILE = os.environ.get("TIKTOK_BROWSER_PROFILE") or config.get("browser_profile", "chrome152")


def browser_profile() -> str:
    name = _browser.get() or _DEFAULT_PROFILE
    if name not in _SPECS:
        raise ValueError("browser_profile: допустимы chrome152 и firefox155.")
    return name


@contextlib.contextmanager
def use_browser_profile(name: str):
    if name not in _SPECS:
        raise ValueError("browser_profile: допустимы chrome152 и firefox155.")
    token = _browser.set(name)
    try:
        yield
    finally:
        _browser.reset(token)


def __getattr__(name):
    profile = browser_profile()
    if name in ("BROWSER_PROFILE", "IMPERSONATE"):
        return profile
    if name in _SPECS[profile]:
        value = _SPECS[profile][name]
        return dict(value) if isinstance(value, dict) else value
    raise AttributeError(name)


def fetch_headers(site: str = "same-origin") -> dict:
    """Заголовки fetch/XHR уже открытой страницы — поверх заголовков сессии.

    Без них curl_cffi под impersonate подставляет набор НАВИГАЦИИ: Site none,
    Mode navigate, Dest document, Sec-Fetch-User ?1, Upgrade-Insecure-Requests
    и Priority u=0, i. POST с таким набором настоящий Chrome не шлёт никогда.
    None убирает заголовок совсем, а не шлёт пустым. Имена — с заглавной:
    строчные curl_cffi не сливает со своими и оставляет навигационные рядом.

    site — same-origin для www.tiktok.com со страницы www, same-site для
    соседнего поддомена (login-us.www.tiktok.com, web-sg.tiktok.com),
    cross-site для чужого домена (mssdk на tiktokw.us).

    Accept — */*, как у fetch без явного Accept (иначе curl_cffi шлёт строку
    навигации text/html…); запросу со своим Accept его ставят поверх. Сверено с
    эталонным Chrome 150: the regression checks"""
    return {
        "Accept": "*/*",
        "Cache-Control": None,
        "Sec-Fetch-Site": site,
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-User": None,
        "Upgrade-Insecure-Requests": None,
        "Priority": "u=4" if __getattr__("IS_FIREFOX") else "u=1, i",
        # firefox155 curl_cffi добавляет te:trailers даже в HTTP/1.1;
        # локальный Firefox fetch его не посылал.
        **({"TE": None} if __getattr__("IS_FIREFOX") else {}),
    }


def browser_headers(accept_language: str = "en-US,en;q=0.9") -> dict:
    """UA, язык и client hints — для проверок прокси, где аккаунта нет."""
    return {"User-Agent": __getattr__("UA"), "Accept-Language": accept_language,
            **__getattr__("SEC_CH_UA")}


# Заголовки, которые ставит сам JS страницы и из-за которых Chrome шлёт перед
# запросом на другой хост CORS-preflight (OPTIONS). Остальное — Sec-*, UA,
# Priority, Referer, Origin — браузер ставит сам, в список они не попадают;
# Accept и Content-Type формы — «простые», тоже не попадают.
_SIMPLE_CT = ("application/x-www-form-urlencoded", "multipart/form-data", "text/plain")
_BROWSER_SET = {"user-agent", "referer", "origin", "priority", "accept",
                "accept-language", "accept-encoding", "cookie", "host",
                "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform",
                "sec-fetch-site", "sec-fetch-mode", "sec-fetch-dest",
                "sec-fetch-user", "sec-fetch-storage-access",
                "upgrade-insecure-requests", "content-length"}


class CorsError(ValueError):
    """Страница не получила разрешение CORS; это не сбой сети."""
    network = False

    def __init__(self, reason: str, code: int = None, *, stop_account=False):
        self.reason = reason
        self.code = code
        self.stop_account = stop_account
        super().__init__("TikTok не разрешил запрос страницы (CORS) — запрос остановлен")


def _header(headers, name):
    return next((value for key, value in headers.items() if key.lower() == name), None)


def _origin(url):
    parsed = urlsplit(url)
    return parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.port or (443 if parsed.scheme == "https" else 80)


def _cors_permission(response, origin, method, author, credentialed):
    if not 200 <= response.status_code < 300:
        raise CorsError("preflight_http_status", response.status_code)
    allowed = _header(response.headers, "access-control-allow-origin")
    if allowed != origin and not (allowed == "*" and not credentialed):
        raise CorsError("allow_origin", response.status_code)
    if credentialed and _header(response.headers, "access-control-allow-credentials") != "true":
        raise CorsError("allow_credentials", response.status_code)
    methods = {part.strip() for part in (_header(response.headers, "access-control-allow-methods") or "").split(",")}
    if method not in {"GET", "HEAD", "POST"} and method not in methods and not ("*" in methods and not credentialed):
        raise CorsError("allow_method", response.status_code)
    allowed_headers = {part.strip().lower() for part in (_header(response.headers, "access-control-allow-headers") or "").split(",")}
    wildcard = "*" in allowed_headers and not credentialed
    if any(name not in allowed_headers and not (wildcard and name != "authorization") for name in author):
        raise CorsError("allow_headers", response.status_code)


def preflight(session, method: str, url: str, headers: dict, referer: str,
              site: str = "same-site", timeout=None, *, strict=False,
              credentialed=False) -> None:
    """CORS-preflight, который Chrome шлёт перед запросом страницы www на
    другой хост, если JS поставил свои заголовки (эталон Chrome 150 — перед
    каждым паспортным шагом на login-us/web-sg и каждой загрузкой на TOS:
    адреса каждый раз разные, кэш preflight не срабатывает).

    headers — заголовки самого запроса; в Access-Control-Request-Headers
    уходят те, что ставит JS: по алфавиту, строчными, через запятую. Нет
    таких — preflight не нужен, как и браузеру. В самом OPTIONS нет ни кук,
    ни client hints; Set-Cookie его ответа браузер не хранит (запрос без
    учётных данных) — jar после него ровно тот, что до. Разрешение Chrome
    помнит на Access-Control-Max-Age (не дольше 2 часов) для того же адреса,
    метода и заголовков — повтор на тот же адрес (pre_connect) идёт без OPTIONS."""
    author = sorted({k.lower() for k, v in headers.items() if v is not None
                     and k.lower() not in _BROWSER_SET
                     and not (k.lower() == "content-type"
                              and str(v).split(";")[0].strip().lower() in _SIMPLE_CT)})
    if not author:
        return
    origin = _header(headers, "origin") if strict else "https://www.tiktok.com"
    key = (method.upper(), url, ",".join(author), origin, credentialed)
    cache = getattr(session, "tt_preflight", None)
    if cache is None:
        cache = session.tt_preflight = {}
    if cache.get(key, 0) > time.time():
        return
    hdrs = {**fetch_headers(site), "Accept": "*/*",
            "Access-Control-Request-Method": method.upper(),
            "Access-Control-Request-Headers": ",".join(author),
            "Origin": origin, "Referer": referer,
            "sec-ch-ua": None, "sec-ch-ua-mobile": None, "sec-ch-ua-platform": None}
    kept = list(session.cookies.jar)
    session.cookies.jar.clear()
    try:
        r = session.request("OPTIONS", url, headers=hdrs, timeout=timeout or (20, 20),
                            allow_redirects=False)
        if r.status_code in (403, 429) or any(
                key.lower() in {"bdturing-verify", "x-tt-verify-idv-decision-conf"}
                for key in r.headers):
            raise CorsError("preflight_platform_refusal", r.status_code, stop_account=True)
        if strict:
            _cors_permission(r, origin, method.upper(), author, credentialed)
        try:
            age = max(0, int(_header(r.headers, "access-control-max-age") or 5))
        except (TypeError, ValueError):
            age = 0
        if age:
            cache[key] = time.time() + min(age, 7200)
    except Exception as exc:  # noqa: BLE001 — не ответил: сам запрос скажет, что не так
        if strict or getattr(exc, "stop_account", False):
            raise
    finally:
        session.cookies.jar.clear()
        for cookie in kept:
            session.cookies.jar.set_cookie(cookie)


def cors_post(session, url: str, headers: dict, site: str = "same-site",
              credentials=None, **kw):
    """POST страницы www на другой хост — сначала preflight, как у Chrome.
    Referer preflight — тот же, что у самого запроса."""
    origin = _header(headers, "origin")
    if credentials not in {None, "include"}:
        raise ValueError("Неизвестный режим учётных данных CORS")
    if origin and _origin(origin) == _origin(url):
        return session.post(url, headers=headers, **kw)
    credentialed = credentials == "include"
    if origin and credentials is None:
        host = urlsplit(url).hostname or ""
        path = urlsplit(url).path or "/"
        secure = urlsplit(url).scheme == "https"
        credentialed = bool(_header(headers, "cookie")) or any(
            (host == cookie.domain.lstrip(".") or (cookie.domain_initial_dot and host.endswith(cookie.domain)))
            and path.startswith(cookie.path or "/") and (not cookie.secure or secure)
            for cookie in session.cookies.jar)
    preflight(session, "POST", url, headers, _header(headers, "referer") or "https://www.tiktok.com/",
              site, kw.get("timeout"), strict=bool(origin), credentialed=credentialed)
    return session.post(url, headers=headers, **kw)
