"""Proxy selection, validation and leases."""
import hashlib
import re
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import config, eventlog, humanize

CHECK_URL = "https://www.tiktok.com/robots.txt"
# подключение с туннелем через прокси — у всех запросов программы, кортежем
# (CONNECT_TIMEOUT, чтение): очередь провайдера доходит до 8–10 с, здесь вдвое
CONNECT_TIMEOUT = 20
PING_TIMEOUT = 5      # ответ самого прокси: десятки мс напрямую, сотни через VPN
PING_TRIES = 2
READ_TIMEOUT = 15
CHECK_TRIES = 2       # попыток на проверку: второй узел ротационного прокси
CHECK_WORKERS = 32    # проверок разом — весь список одним заходом

FAILS_TO_CHECK = 3    # сетевых сбоев из работы подряд -> перепроверка
RECHECK_MIN = 30      # мёртвый перепроверяется через столько секунд,
RECHECK_MAX = 120     # дальше реже, но не реже этого
STALE_SEC = 20        # свежесть вердикта «мёртв», когда мёртвы все
WAIT_RECHECK = 15     # пока ждём живой прокси — проверяем не чаще
WAIT_SEC = 300        # сколько ждать, пока оживёт хоть один

AUTO_CHECK_SEC = 300  # сами берёмся за строку: вердикта нет или он старше
AUTO_CHECK_TICK = 30  # как часто просыпается фоновый поток (замер — проба)

COUNTRY_URL = "https://www.tiktok.com/signup"  # тот же адрес, что у _warm_once
COUNTRY_TTL_SEC = 24 * 60 * 60  # вердикт свежий сутки — у ротационных прокси
                                 # IP меняется, а с ним и страна
COUNTRY_MAX_BYTES = 200_000      # поле "region" не нашлось — не читаем страницу
                                 # целиком (она — 360 КБ)

NO_ALIVE = "ни один прокси не отвечает — проверьте раздел «Прокси»"


class NoAliveProxy(RuntimeError):
    """Прокси включены, но ни один не отвечает."""


class ProxySelectionError(NoAliveProxy):
    """Для дела не отмечена ни одна активная прокси."""


_lock = threading.Lock()
_health = {}          # адрес прокси -> состояние (см. _entry)
_checking = set()     # адреса, которые проверяются прямо сейчас
_watch = None         # поток перепроверки мёртвых
_auto = None          # поток автопроверки устаревших (см. _auto_loop)
_wait_said = 0.0      # когда в ленту последний раз писали «ждём прокси»


def short(url: str) -> str:
    """host:port без схемы, логина и пароля — для ленты и интерфейса."""
    return (url or "").rsplit("@", 1)[-1].split("://")[-1]


TASK_KEYS = {
    "login": "proxies_login",
    "publish": "proxies_publish",
}   # дело -> ключ настроек с его набором
TASK_SELECTION_ERRORS = {
    "login": "для входа не выбрана ни одна прокси — отметьте хотя бы одну в разделе «Прокси»",
    "publish": "для публикации не выбрана ни одна прокси — отметьте хотя бы одну в разделе «Прокси»",
}


def configured(task: str = None) -> list:
    """Прокси из настроек в порядке списка. [] — прокси выключены или список
    пуст: тогда работа идёт с прямого IP, так решил пользователь. Тумблер
    читается через `proxies.as_bool`: строкой его не перевернуть.
    Умолчание False — то же, что и раньше значил пустой ключ; настоящий
    config его всегда несёт (config.load подмешивает DEFAULTS).

    `task` — под какое дело просят ("login" или "publish"). У дела может
    быть свой набор прокси (`TASK_KEYS`); тогда отдаём общий список, оставив
    в нём только отмеченные, — ПОРЯДОК берём из общего списка, чтобы
    «наименее занятый, при равенстве раньше в списке» считался одинаково
    везде. Набор должен быть задан явно: если в нём нет ни одной активной
    строки общего списка, бросаем ProxySelectionError. Брать случайную прокси
    из общего списка нельзя — у входа и публикации могут быть разные IP.

    Фильтр стоит здесь намеренно: `configured()` — единственная дверь, через
    которую пул узнаёт список, и её зовут и аренда, и выбор, и пересадка при
    сбое. Отфильтруй мы в одной только аренде — пересадка увела бы вход на
    чужой прокси при первом же обрыве."""
    from . import proxies
    if not proxies.as_bool(config.get("proxy_enabled"), False):
        return []
    items = [p.strip() for p in (config.get("proxies") or [])
             if isinstance(p, str) and p.strip()]
    # выключенные строки не идут в работу ВООБЩЕ — ни общим списком, ни набором
    # дела: отсекаем их здесь, до любых наборов, иначе выключенная прокси
    # осталась бы единственной «отмеченной на вход» и вход шёл бы через неё
    off = {p.strip() for p in (config.get("proxies_off") or [])
           if isinstance(p, str) and p.strip()}
    if off:
        items = [u for u in items if u not in off]
    if not items:
        single = config.get("proxy")
        items = [single.strip()] if isinstance(single, str) and single.strip() else []
    key = TASK_KEYS.get(task or "")
    if not key:
        return items
    picked = {p.strip() for p in (config.get(key) or [])
              if isinstance(p, str) and p.strip()}
    selected = [u for u in items if u in picked]
    if not selected:
        raise ProxySelectionError(TASK_SELECTION_ERRORS[task])
    return selected


def _entry(url: str) -> dict:
    """Состояние прокси; звать под _lock."""
    entry = _health.get(url)
    if entry is None:
        entry = _health[url] = {"state": "unknown", "scheme": "", "ms": None,
                                "ping": None, "error": "", "checked_at": 0.0,
                                "fails": 0, "country": None, "org": ""}
    return entry


def _pulse() -> None:
    """Состояние поменялось — живой поток UI пришлёт свежие отметки."""
    eventlog.pulse("proxies")


# --- проверка ---------------------------------------------------------------

def _hello(scheme: str) -> bytes:
    """Первое сообщение прокси, на которое он отвечает сам, не открывая туннель:
    HTTP — CONNECT без пароля (у прокси с паролем ответ 407 приходит сразу),
    SOCKS5 — приветствие со списком способов входа. socks4 такого не умеет —
    для него пинг считается по одному подключению."""
    if scheme.startswith("socks5"):
        return b"\x05\x01\x00"
    if scheme in ("http", "https"):
        host = CHECK_URL.split("://", 1)[1].split("/", 1)[0]
        return f"CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n\r\n".encode()
    return b""


def _ping(url: str, entry=None) -> tuple:
    """Пинг самого прокси: (миллисекунды, "") или (None, причина).

    Мерится время до ответа прокси на первое сообщение (_hello), а не время
    TCP-подключения. VPN в режиме TUN (замер 14.09.2026, Happ) сам принимает
    любое подключение за 1 мс — живой прокси и «чёрная дыра» по connect()
    неотличимы, а настоящий ответ прокси через VPN — 200–350 мс. У
    ротационного прокси это пинг до его входа, путь до TikTok показывает время
    ответа. Две попытки: VPN изредка поднимает подключение дольше PING_TIMEOUT.
    entry — уже разобранный адрес: проверка разбирает строку один раз на все
    свои шаги."""
    from . import proxies
    if entry is None:
        entry, err = proxies.parse_line(url)
        if entry is None:
            return None, err or "не удалось разобрать адрес прокси"
    try:
        addrs = socket.getaddrinfo(entry.host, entry.port, type=socket.SOCK_STREAM)
    except OSError:
        return None, "адрес не найден — нет интернета или прокси указан неверно"
    hello = _hello(entry.scheme)
    reason = ""
    for attempt in range(PING_TRIES):
        family, kind, proto, _, addr = addrs[attempt % len(addrs)]
        sock = socket.socket(family, kind, proto)
        sock.settimeout(PING_TIMEOUT)
        started = time.monotonic()
        try:
            sock.connect(addr)
            if hello:
                started = time.monotonic()
                sock.sendall(hello)
                sock.recv(64)  # любой ответ, даже закрытое соединение, — прокси на месте
            return max(1, round((time.monotonic() - started) * 1000)), ""
        except socket.timeout:
            reason = "прокси не ответил вовремя"
        except OSError:
            reason = "прокси не отвечает — проверьте адрес и порт"
        finally:
            sock.close()
    return None, reason


def _probe(url: str) -> dict:
    """Один заход проверки, без исключений: {"ok", "ms", "ping", "scheme",
    "error"}, у успешного заодно "country". ms — время ответа TikTok через
    прокси, ping — до самого прокси, scheme — определённый тип прокси
    (пусто — схему называл пользователь или прокси не признался). country —
    страна по вердикту TikTok, только когда стоило спросить (см.
    _maybe_refresh_country); неуспешный заход её не трогает вовсе — старое
    значение (если было) остаётся в настройках как есть.

    Порядок шагов — тип, потом пинг, потом запрос к TikTok. Тип спрашивается у
    самого прокси только у строки без схемы и обязательно ДО пинга: разбор
    подставил такой строке http, а пинг шлёт первое сообщение по схеме строки
    (_hello) — SOCKS5 на CONNECT отвечает сбросом, и живой прокси признавался
    бы мёртвым, не дойдя ни до своего типа, ни до запроса.
    Определённый тип тут же уходит в пинг: дальше спрашивать надо на его языке."""
    from curl_cffi import requests
    from . import client_device, proxies
    entry, _ = proxies.parse_line(url)
    scheme = ""
    if entry is not None and proxies.needs_detect(url):
        scheme = proxies.detect(entry.host, entry.port, entry.user, entry.password)
        if scheme:
            print(f"[proxy] {short(url)}: тип определён — {scheme}")
            entry.scheme = scheme
    ping, error = _ping(url, entry)
    if ping is None:
        print(f"[proxy] проверка {short(url)}: пинг не прошёл — {error}")
        return {"ok": False, "ms": None, "ping": None, "scheme": scheme,
                "error": error}
    for _ in range(CHECK_TRIES):
        started = time.monotonic()
        try:
            requests.get(CHECK_URL, proxies={"all": _remote_dns(url)},
                         timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                         impersonate=client_device.IMPERSONATE)
            # прокси жив — можно спросить страну; на мёртвом смысла нет
            # (второй такой же таймаут), поэтому только здесь, не выше
            country = _maybe_refresh_country(url, entry)
            rotation(url)
            # оператор — подпись в строке, а ipinfo бесплатно отвечает ~50 тыс.
            # раз в месяц: спрашиваем, только пока его не знаем или когда
            # переспрашивали страну (смена IP, раз в сутки), а не на каждой проверке
            with _lock:
                known_org = _entry(url)["org"]
            org = exit_geo(url).get("org", "") if (country or not known_org) else ""
            return {"ok": True, "error": "", "ping": ping, "scheme": scheme,
                    "country": country, "org": org,
                    "ms": int((time.monotonic() - started) * 1000)}
        except Exception as exc:  # noqa: BLE001 — любой сбой = вердикт, не падение
            print(f"[proxy] проверка {short(url)}: {type(exc).__name__}: {exc}")
            error = humanize.error(exc)
            if error in humanize.PROXY_REFUSED:
                break  # прокси жив, но не пускает — второй заход не поможет
    return {"ok": False, "ms": None, "ping": ping, "scheme": scheme, "error": error}


def _rescheme(url: str, scheme: str) -> str:
    """Заменить схему в каноническом адресе на найденную работой. url всегда
    несёт схему (parse_line её подставляет), а для строки, которую detect()
    вообще спрашивали (needs_detect), подставленная схема — всегда "http"
    (см. _parse_endpoint): другого варианта разбор не подставляет."""
    if "://" not in url:
        return url
    return f"{scheme}://{url.split('://', 1)[1]}"


def _apply_detected_scheme(url: str, scheme: str) -> str:
    """_probe узнал тип строки, для которой пользователь схему не
    называл (config хранит подставленный http), — переписываем адрес найденной
    схемой в config сразу, во всех местах, где он встречается как значение или
    ключ: список, наборы login/publish/off, ссылка ротации. Без этого отметка
    в UI говорит "socks5", а вход и публикация продолжают ходить по http.

    Возвращает новый адрес, если что-то переписано, иначе "" — схема не
    поменялась или список сменили за время проверки (строки уже нет)."""
    new_url = _rescheme(url, scheme)
    if new_url == url:
        return ""
    cfg = config.load()
    proxies_list = cfg.get("proxies") or []
    if url not in proxies_list:
        return ""
    patch = {"proxies": [new_url if u == url else u for u in proxies_list]}
    replace_keys = []
    for key in ("proxies_login", "proxies_publish", "proxies_off"):
        items = cfg.get(key) or []
        if url in items:
            patch[key] = [new_url if u == url else u for u in items]
    rot = cfg.get("proxy_rotate_urls")
    if isinstance(rot, dict) and url in rot:
        new_rot = dict(rot)
        new_rot[new_url] = new_rot.pop(url)
        patch["proxy_rotate_urls"] = new_rot
        replace_keys.append("proxy_rotate_urls")
    config.update(patch, replace=tuple(replace_keys))
    with _lock:
        entry = _health.pop(url, None)
        if entry is not None:
            _health[new_url] = entry
        if url in _leases:
            _leases[new_url] = _leases.pop(url)
    print(f"[proxy] {short(url)}: адрес в config переписан под определённую "
          f"схему ({scheme})")
    return new_url


# --- страна прокси: вердикт TikTok, не сторонний geo-сервис -----------------

def _country_key(url: str, parsed=None) -> str:
    """Ключ в config.proxy_countries: канонический адрес ПЛЮС короткий
    отпечаток учётки. parsed — уже разобранная строка, если под рукой (снимок
    разбирает её один раз на всё).

    Одного адреса мало, в отличие от proxy_scheme_named. Тип прокси — свойство
    шлюза, он у всех строк с одним host:port общий. А страна — свойство
    ВЫХОДНОГО адреса, и у каждой учётки того же шлюза он свой: у владельца две
    строки на `proxy.noshadow.pro:9696`, различаются только логином с паролем,
    и по одному адресу они делили бы одну запись, затирая вердикт друг друга.
    Особенно заметно станет, когда на том же шлюзе заведут европейскую учётку
    под вход.

    Сама учётка в настройки не попадает: только необратимый отпечаток, восемь
    шестнадцатеричных знаков от sha256. Учётки нет — суффикса нет вовсе: адрес
    и так уникален, а прежние записи остаются читаемыми."""
    entry = parsed
    if entry is None:
        from . import proxies
        entry, _ = proxies.parse_line(url)
    if entry is None:
        return short(url)
    secret = f"{entry.user}:{entry.password}"
    if secret == ":":
        return entry.safe
    mark = hashlib.sha256(secret.encode("utf-8")).hexdigest()[:8]
    return f"{entry.safe}#{mark}"


def _country_record(rec) -> tuple:
    """(код страны, возраст вердикта в секундах) из одной записи
    config.proxy_countries; (None, None) — записи нет или она кривая
    (руками поправили config.json) — тогда просто считается «не знаем»."""
    if not isinstance(rec, dict):
        return None, None
    code = rec.get("code")
    if not isinstance(code, str) or len(code) != 2:
        return None, None
    try:
        age = time.time() - float(rec.get("at"))
    except (TypeError, ValueError):
        age = None
    return code.upper(), age


def _country_load(key: str) -> tuple:
    """(код, возраст) из настроек — читает config сам. Звать только ВНЕ
    _lock (проверка живости, _probe, идёт без него): под замком пула файл
    не читаем — там страну берёт _country_for из готового ctx."""
    data = config.get("proxy_countries")
    rec = data.get(key) if isinstance(data, dict) else None
    return _country_record(rec)


class _Writes:
    """Записи в config за один проход check_all: копятся и уходят одним
    config.update в конце, а не файлом на каждую строку списка.

    Копит только вид {ключ: {запись: значение}} (proxy_countries,
    proxy_rotation) — такие патчи config сливает вглубь, и слияние здесь то же.
    Сдвиг один: пока проход не кончился, другой поток видит вердикт строки не
    в файле, а в памяти пула, — худшее, что от этого бывает, одна лишняя
    проверка той же строки."""

    def __init__(self):
        self._lock = threading.Lock()
        self._data = {}

    def add(self, patch: dict) -> None:
        with self._lock:
            for key, records in patch.items():
                self._data.setdefault(key, {}).update(records)

    def flush(self) -> None:
        with self._lock:
            data, self._data = self._data, {}
        if data:
            config.update(data)


_tls = threading.local()  # .writes — накопитель проверки, которая идёт в этом потоке


def _config_write(patch: dict) -> None:
    """Записать патч в config: сразу, а внутри check_all — в общий накопитель."""
    writes = getattr(_tls, "writes", None)
    if writes is None:
        config.update(patch)
    else:
        writes.add(patch)


def _country_save(key: str, code: str) -> None:
    _config_write({"proxy_countries": {key: {"code": code, "at": time.time()}}})


def _country_drop(key: str) -> None:
    """Прежний вердикт больше не про этот адрес (IP сменился) — убрать
    только его запись, остальные строки не трогаем."""
    data = config.get("proxy_countries")
    if not isinstance(data, dict) or key not in data:
        return
    rest = {k: v for k, v in data.items() if k != key}
    config.update({"proxy_countries": rest}, replace=("proxy_countries",))


def forget_country(entry) -> None:
    """IP только что сменился по ссылке провайдера (proxies.rotate) —
    прежний вердикт страны был про старый адрес, а не про этот. Звать сразу
    после успешной смены; дальше страну переспросит очередная проверка
    живости. entry — ProxyEntry; None молча пропускается.

    Ключ считается тем же _country_key, что и при записи: у одного шлюза
    несколько строк, и сбросить надо вердикт ТОЙ, у которой сменился IP, а не
    общий на всех."""
    if entry is None:
        return
    _country_drop(_country_key("", entry))


def _country_probe(url: str) -> str:
    """Двухбуквенный код страны прокси по вердикту TikTok на /signup, "" —
    не узнали (сеть, WAF, поле не нашлось). Наружу исключения не пускает —
    страна необязательна, проверку живости она не роняет.

    Приём — как у прогрева анонимной личности (modules/profiles.py,
    _warm_once): поток и обрыв чтения на первом совпадении, страница целиком
    не читается. Там это асинхронно (httpx-подобная сессия curl_cffi), здесь
    синхронно — вся проверка живости синхронная."""
    from curl_cffi import requests
    from . import client_device, profiles  # region-регекс — тот же, что у _warm_once
    try:
        with requests.Session() as s:
            r = s.get(COUNTRY_URL, stream=True, proxies={"all": _remote_dns(url)},
                       timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                       impersonate=client_device.IMPERSONATE,
                       # Accept навигации — curl_cffi под impersonate, как у Chrome
                       headers=dict(client_device.browser_headers(),
                                    **{"Upgrade-Insecure-Requests": "1"}))
            try:
                buf = ""
                for chunk in r.iter_content():
                    buf += chunk.decode("utf-8", "ignore")
                    m = profiles._REGION_RE.search(buf)
                    if m:
                        return m.group(1)
                    if len(buf) > COUNTRY_MAX_BYTES:
                        break
            finally:
                r.close()
    except Exception as exc:  # noqa: BLE001 — страна необязательна, молчим
        print(f"[proxy] страна {short(url)}: {type(exc).__name__}: {exc}")
    return ""


def _maybe_refresh_country(url: str, entry) -> str:
    """Код страны прокси, обновив вердикт по правилам (см. шапку модуля):
    не знаем или вердикт старше COUNTRY_TTL_SEC — переспросить у TikTok и
    запомнить. Возвращает то, что теперь знаем ("" — не знаем и не вышло
    узнать). Сбой запроса не стирает старое значение — оно и возвращается."""
    key = _country_key(url, entry)
    code, age = _country_load(key)
    if code is not None and age is not None and age < COUNTRY_TTL_SEC:
        return code
    fresh = _country_probe(url)
    if fresh:
        _country_save(key, fresh)
        return fresh
    return code or ""


def _country_for(key: str, ctx: dict) -> str:
    """Страна прокси для отметки UI — то, что уже знаем (пусть и не совсем
    свежее), из готового ctx (не файл — см. _country_load); None — не знаем
    ещё."""
    return _country_record((ctx.get("countries") or {}).get(key))[0]


def check(url: str, ctx: dict = None) -> dict:
    """Проверить один прокси и запомнить вердикт. Возвращает отметку, как в
    snapshot(). Потоко-безопасна; одновременные проверки одного адреса не
    мешают друг другу — просто последняя перезапишет вердикт. ctx — уже
    прочитанные настройки (_ui_context): проверка списка отдаёт один на всех,
    чтобы config не перечитывался по разу на строку. Словарь может быть и
    неполным — чего в нём нет, берётся само (чужой ctx без ссылок не роняет
    проверку, ).

    Определённую _probe схему (строка без схемы в config) сразу переписываем
    в config (_apply_detected_scheme, ) — иначе отметка в UI говорит
    "socks5", а вход и публикация продолжают ходить по подставленному http.
    Дальше в этой же проверке работаем уже с переписанным адресом."""
    ctx = ctx or _ui_context()
    parsed = _parsed(url, ctx)
    checking_key = url
    with _lock:
        _checking.add(checking_key)
    _pulse()
    result = {"ok": False, "ms": None, "ping": None, "scheme": "",
              "error": "проверка не состоялась"}
    try:
        result = _probe(url)
        if result.get("scheme"):
            reschemed = _apply_detected_scheme(url, result["scheme"])
            if reschemed:
                url = reschemed
                # login/publish/off в ctx ещё про старый адрес — сам ctx мог
                # быть общим на весь check_all(), поэтому только у себя
                ctx = _ui_context()
                parsed = _parsed(url, ctx)
    finally:
        with _lock:
            _checking.discard(checking_key)
            entry = _entry(url)
            was = entry["state"]
            entry.update(state="ok" if result["ok"] else "dead", ms=result["ms"],
                         ping=result.get("ping"), error=result["error"],
                         checked_at=time.time())
            if result.get("scheme"):
                entry["scheme"] = result["scheme"]
            if result.get("country"):
                entry["country"] = result["country"]
            if result.get("org"):
                entry["org"] = result["org"]
            if result["ok"]:
                entry["fails"] = 0
            mark = _mark(url, entry, ctx, parsed)
        if result["ok"] and was == "dead":
            eventlog.say(f"прокси {short(url)} снова отвечает", "ok", source="proxy")
        elif not result["ok"] and was != "dead":
            eventlog.say(f"прокси {short(url)} не отвечает: {result['error']}",
                         "err", source="proxy")
        if not result["ok"]:
            _ensure_watch()
        _pulse()
    return mark


def check_all(urls=None) -> list:
    """Проверить список разом (по умолчанию — прокси из настроек). Ждёт всех:
    на мёртвом прокси это CONNECT_TIMEOUT на попытку, на живом — секунды.

    Страна и вид смены IP, найденные по ходу, пишутся в config одним разом в
    конце прохода (_Writes), даже если проход оборвался. Схема, определённая у
    строки без неё, переписывается сразу — это редкая правка адресов списка."""
    urls = configured() if urls is None else [u for u in urls if u]
    if not urls:
        return []
    ctx = _ui_context()
    writes = _Writes()

    def one(url: str) -> dict:
        _tls.writes = writes
        try:
            return check(url, ctx)
        finally:
            _tls.writes = None

    try:
        with ThreadPoolExecutor(max_workers=min(CHECK_WORKERS, len(urls))) as pool:
            return list(pool.map(one, urls))
    finally:
        writes.flush()


# --- сигналы из работы ------------------------------------------------------

def report_ok(url: str) -> None:
    """Через прокси прошёл запрос — он жив, счёт сбоев с нуля."""
    if not url:
        return
    with _lock:
        entry = _entry(url)
        revived = entry["state"] == "dead"
        changed = entry["state"] != "ok"
        entry.update(state="ok", fails=0, error="")
    if revived:
        eventlog.say(f"прокси {short(url)} снова отвечает", "ok", source="proxy")
    if changed:
        _pulse()


def report_fail(url: str, reason="", count: int = 1) -> None:
    """Сетевой сбой запроса через прокси. Звать только на сбоях сети или
    прокси — капча и отказы TikTok сюда не относятся. count — сколько сбоев
    засчитать разом (у анонимки одна ошибка — это уже три попытки подряд).
    Не блокирует: перепроверка уходит в свой поток."""
    if not url:
        return
    if "407" in str(reason):
        count = FAILS_TO_CHECK
    with _lock:
        entry = _entry(url)
        entry["fails"] += count
        due = (entry["fails"] >= FAILS_TO_CHECK and entry["state"] != "dead"
               and url not in _checking)
        if due:
            entry["fails"] = 0
            _checking.add(url)  # занимаем сразу: соседний сбой вторую не запустит
    if due:
        print(f"[proxy] {short(url)}: сбои подряд — перепроверяю")
        threading.Thread(target=check, args=(url,), name="proxy-check",
                         daemon=True).start()


# --- выбор ------------------------------------------------------------------

def _usable(urls) -> list:
    with _lock:
        return [u for u in urls if _entry(u)["state"] != "dead"]


def _claim(urls, min_age: float, skip=None) -> list:
    """Забрать на проверку тех, кого сейчас никто не проверяет и чей вердикт
    старше min_age. Занимаем под тем же замком: тысяча воркеров, разом
    увидевших «мёртвы все», не запускают тысячу одинаковых проверок.

    skip — дополнительное условие «не брать»; зовётся под тем же замком, им
    пользуется фон, чтобы не отнять строку у аренды (_busy)."""
    now = time.time()
    with _lock:
        due = [u for u in urls if u not in _checking
               and not (skip and skip(u))
               and now - _entry(u)["checked_at"] >= min_age]
        _checking.update(due)
    return due


def _await_checks(urls, timeout: float) -> None:
    """Дождаться проверок, которые по этим адресам уже идут в других потоках."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with _lock:
            if not any(u in _checking for u in urls):
                return
        time.sleep(0.5)


def is_dead(url: str) -> bool:
    with _lock:
        return bool(url) and _entry(url)["state"] == "dead"


def _alive_now(recheck: bool, task: str = None) -> tuple:
    """(прокси из настроек, живые из них). Мёртвы все и recheck — перед
    отказом перепроверить тех, чей вердикт старше STALE_SEC: блокирует до
    пары десятков секунд, из event loop звать с recheck=False.
    `task` — под какое дело просят (см. configured)."""
    urls = configured(task)
    if not urls:
        return urls, []
    alive = _usable(urls)
    if not alive and recheck:
        due = _claim(urls, STALE_SEC)
        if due:
            check_all(due)
        _await_checks(urls, CHECK_TRIES * (CONNECT_TIMEOUT + READ_TIMEOUT))
        alive = _usable(urls)
    return urls, alive


def pick(recheck: bool = True, task: str = None) -> str:
    """Первый живой прокси списка — тому, кому важен один и тот же IP, пока он
    жив (анонимная личность). "" — прокси выключены или список пуст; мёртвы
    все — NoAliveProxy. Работе с аккаунтами — lease(): она раскладывается по
    занятости. `task` — под какое дело просят (см. configured)."""
    urls, alive = _alive_now(recheck, task)
    if not urls:
        return ""
    if not alive:
        raise NoAliveProxy(NO_ALIVE)
    return alive[0]


# --- аренда: раздача по занятости -------------------------------------------
#
# Раньше аккаунт получал прокси по номеру в очереди (proxies[i % len]). Номер
# ничего не знает о том, кто сейчас работает: при 5 потоках на 5 прокси
# восьмой аккаунт садился на прокси третьего, пока тот ещё публиковал, — два
# аккаунта на одном IP при свободных соседях. Аренда считает, сколько дел
# сейчас идут через каждый прокси, и выдаёт наименее занятый живой.

_leases = {}          # адрес прокси -> сколько дел сейчас через него идут


def _least_busy(candidates, urls) -> str:
    """Наименее занятый; при равенстве — раньше в списке. Звать под _lock."""
    order = {u: i for i, u in enumerate(urls)}
    return min(candidates, key=lambda u: (_leases.get(u, 0), order.get(u, 0)))


def _drop(url: str) -> None:
    """Минус одно дело на прокси. Звать под _lock."""
    left = _leases.get(url, 0) - 1
    if left > 0:
        _leases[url] = left
    else:
        _leases.pop(url, None)


def _busy(url: str) -> int:
    """Сколько дел идут через прокси сейчас (0 — свободен). Звать под _lock."""
    return _leases.get(url, 0)


class Lease:
    """Прокси, закреплённый за одним делом (аккаунтом, входом, чисткой) до
    release(). url — текущий прокси, "" — прокси выключены: работа с прямого
    IP, так решил пользователь."""

    def __init__(self, url: str = "", task: str = None):
        self.url = url
        self.task = task     # под какое дело снята: пересадка не выходит за набор
        self._held = bool(url)

    def swap(self) -> bool:
        """Пересесть на другой живой прокси, наименее занятый. False — другого
        живого нет, остаёмся на текущем. Пересадка идёт по набору СВОЕГО дела:
        аренда под вход не уедет на прокси, которым входить не разрешали."""
        if not self._held:
            return False
        urls = configured(self.task)
        with _lock:
            others = [u for u in urls if u != self.url and _entry(u)["state"] != "dead"]
            if not others:
                return False
            new = _least_busy(others, urls)
            _drop(self.url)
            _leases[new] = _leases.get(new, 0) + 1
            self.url = new
        _pulse()
        return True

    def release(self) -> None:
        """Дело закончено — прокси освобождается. Повторный вызов безопасен."""
        with _lock:
            if not self._held:
                return
            _drop(self.url)
            self._held = False
        _pulse()


def lease(recheck: bool = True, task: str = None) -> Lease:
    """Наименее занятый живой прокси, закреплённый за делом до release().
    Прокси выключены или список пуст — Lease с пустым url; включены, а живых
    нет — NoAliveProxy (recheck — как у _alive_now).

    `task` — под какое дело просят (см. configured). Дело запоминается в самой
    аренде: пересадка при сбое обязана остаться внутри того же набора, иначе
    вход, начатый с европейской прокси, после первого обрыва доснимется с
    чужой — и регион аккаунта окажется не тот, ради которого всё затевалось."""
    urls, alive = _alive_now(recheck, task)
    if not urls:
        return Lease("", task)
    if not alive:
        raise NoAliveProxy(NO_ALIVE)
    with _lock:
        # вердикты могли смениться, пока шли проверки
        alive = [u for u in alive if _entry(u)["state"] != "dead"] or alive
        url = _least_busy(alive, urls)
        _leases[url] = _leases.get(url, 0) + 1
    _pulse()
    return Lease(url, task)


# --- смерть прокси посреди дела ------------------------------------------------
#
# Что делать, когда прокси умер, пока через него шла публикация, решает
# пользователь (вкладка «Настройки»):
#   swap — пересесть на другой живой, наименее занятый (так было всегда);
#   stop — поток встаёт вместе со своим прокси, и выжившие прокси не
#          уплотняются чужими потоками. Аккаунт, с которым ещё ничего не
#          сделали, забирает другой поток.
# Вход и остальные дела пересаживаются всегда: настройка — про потоки публикации.

ON_DEATH_KEY = "proxy_on_death"
ON_DEATH_SWAP = "swap"
ON_DEATH_STOP = "stop"
ON_DEATH = (ON_DEATH_SWAP, ON_DEATH_STOP)


class ProxyDied(RuntimeError):
    """Прокси публикации умер, а настройка велит остановить поток, а не
    пересаживать. requeue — аккаунт ещё не трогали: его можно отдать
    другому потоку."""

    def __init__(self, url: str, requeue: bool = True):
        super().__init__("прокси %s не отвечает — поток остановлен" % short(url))
        self.url = url
        self.requeue = requeue


def on_death() -> str:
    """Настройка «прокси умер»: ON_DEATH_SWAP или ON_DEATH_STOP."""
    value = config.get(ON_DEATH_KEY)
    return value if value in ON_DEATH else ON_DEATH_SWAP


def _stays(held: Lease) -> bool:
    """Аренда не пересаживается: дело — публикация, и настройка велит
    останавливать поток."""
    return held.task == "publish" and on_death() == ON_DEATH_STOP


def reseat(held: Lease, stop=None, waiting=None, dead: bool = False) -> bool:
    """Дело сорвалось на сети через held.url — куда дальше.

    Пересадка: на другой живой, наименее занятый. Другого нет — остаёмся на
    текущем, если он жив (новое соединение уйдёт через другой узел), мёртв —
    ждём до WAIT_SEC, пока оживёт хоть один.
    Остановка потока: прокси проверяется тут же (dead — уже проверен, мёртв).
    Жив — остаёмся на нём, мёртв — ProxyDied.

    stop() — бросить ожидание; waiting(True/False) — начали/кончили ждать.
    True — held смотрит в прокси, через который можно пробовать заново;
    False — живых не дождались."""
    if not held.url:
        return True
    if _stays(held):
        if dead or check(held.url)["state"] == "dead":
            raise ProxyDied(held.url)
        return True
    while not held.swap():
        if not is_dead(held.url):
            return True
        if stop and stop():
            return False
        if waiting:
            waiting(True)
        try:
            alive = wait_usable(stop=stop, task=held.task)
        finally:
            if waiting:
                waiting(False)
        if not alive:
            return False
    return True


# --- IP аккаунта и где он ------------------------------------------------------
#
# Траст держится на том, что пояс, язык и регион запросов — того места, где IP
# выхода, а не America/New_York у всех при выходе из Техаса или Калифорнии.

GEO_URL = "https://ipinfo.io/json"
GEO_TTL_SEC = 600     # переспрашиваем раз в 10 минут
_geo_cache = {}       # адрес прокси -> (когда спросили, гео)


def _remote_dns(url: str) -> str:
    from . import proxies
    return proxies.remote_dns(url)


# --- как прокси меняет IP -------------------------------------------------------
#
# Вид прокси определяется замером, один раз и на неделю (ROTATION_TTL_SEC):
#   link     — IP меняет ссылка провайдера (у строки есть rotate_url);
#   own      — закрепление IP пользователь прописал в логине сам;
#   static   — два новых соединения дают один IP;
#   rotating — IP меняется на каждом новом соединении.
# Только для показа в разделе «Прокси»: прокси программа не меняет и ни к
# какому виду не принуждает. Хранится рядом со страной, тем же ключом (адрес +
# отпечаток учётки): config.proxy_rotation.
ROTATION_TTL_SEC = 7 * 24 * 60 * 60
IP_URL = "https://api.ipify.org"
_rotation_locks = {}


def _exit_ip(url: str) -> str:
    """IP выхода по НОВОМУ соединению; "" — не узнали, None — логин отвергнут."""
    from curl_cffi import requests
    from . import client_device
    try:
        with requests.Session(impersonate=client_device.IMPERSONATE) as s:
            s.proxies = {"all": _remote_dns(url)}
            return s.get(IP_URL, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT)).text.strip()
    except Exception as exc:  # noqa: BLE001
        return None if "rejected" in str(exc) or "407" in str(exc) else ""


def _rotation_probe(url: str) -> dict:
    """Замер вида прокси (см. выше)."""
    from . import proxies
    entry, _ = proxies.parse_line(url)
    if entry is not None and entry.rotate_url:
        return {"kind": "link"}
    if proxies.has_own_sticky(url):
        return {"kind": "own"}
    first, second = _exit_ip(url), _exit_ip(url)
    if not first or not second:
        return {}                       # не ответила — вердикта нет
    return {"kind": "static" if first == second else "rotating"}


def _rotation_record(url: str, rec) -> dict:
    """Не возвращать прежнее own, если в строке закрепление не задано."""
    from . import proxies
    if not isinstance(rec, dict) or (rec.get("kind") == "own" and not proxies.has_own_sticky(url)):
        return {}
    return rec


def rotation(url: str, refresh: bool = False) -> dict:
    """Вид прокси из настроек; нет или устарел (refresh — принудительно) —
    замер сейчас, один на прокси разом. {} — прокси не ответила."""
    key = _country_key(url)
    data = config.get("proxy_rotation")
    rec = _rotation_record(url, data.get(key) if isinstance(data, dict) else None)
    fresh = isinstance(rec, dict) and time.time() - float(rec.get("at") or 0) < ROTATION_TTL_SEC
    if fresh and not refresh:
        return rec
    with _lock:
        lock = _rotation_locks.setdefault(key, threading.Lock())
    with lock:
        data = config.get("proxy_rotation")
        rec = _rotation_record(url, data.get(key) if isinstance(data, dict) else None)
        if (not refresh and isinstance(rec, dict)
                and time.time() - float(rec.get("at") or 0) < ROTATION_TTL_SEC):
            return rec
        found = _rotation_probe(url)
        if found:
            found["at"] = time.time()
            _config_write({"proxy_rotation": {key: found}})
            print(f"[proxy] {short(url)}: смена IP — {found['kind']}")
        return found or (rec if isinstance(rec, dict) else {})


def exit_geo(url: str) -> dict:
    """Где выход прокси прямо сейчас: {"ip", "country", "tz", "org"}; {} — не узнали.
    Спрашиваем через сам прокси (напрямую был бы наш IP) и помним 10 минут."""
    if not url:
        return {}
    now = time.time()
    with _lock:
        hit = _geo_cache.get(url)
    if hit and now - hit[0] < GEO_TTL_SEC:
        return hit[1]
    from curl_cffi import requests
    from . import client_device
    try:
        with requests.Session(impersonate=client_device.IMPERSONATE) as s:
            s.proxies = {"all": _remote_dns(url)}
            d = s.get(GEO_URL, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT)).json()
        # org у ipinfo — «AS7922 Comcast Cable…»: номер сети человеку ни к чему
        geo = {"ip": d.get("ip", ""), "country": (d.get("country") or "").upper(),
               "tz": d.get("timezone") or "",
               "org": re.sub(r"^AS\d+\s+", "", d.get("org") or "")}
    except Exception as exc:  # noqa: BLE001 — не узнали: профиль останется прежним
        print(f"[proxy] где выход {short(url)} — не узнать: {type(exc).__name__}")
        return {}
    if not (geo["country"] and geo["tz"]):
        return {}
    with _lock:
        _geo_cache[url] = (now, geo)
    return geo


def bind(session, held: Lease) -> None:
    """Пересадка сессии curl_cffi на лету.

    Каждый запрос сессии сообщает исход в пул. Сетевой сбой — и если есть
    другой живой прокси, аренда пересаживается, а следующий запрос этой же
    сессии уходит уже через новый прокси. Своих повторов здесь нет: их хватает
    у вызывающего кода. После защищённого запроса с неизвестным исходом
    маршрут не меняется: ни одинаковое тело, ни creation_id не доказывают,
    что следующая отправка не создаст дубль. GET/HEAD/OPTIONS могут выбрать
    живой маршрут для следующего чтения; этот запрос здесь не повторяется.

    Методы get/post у curl_cffi зовут self.request, поэтому достаточно
    подменить его на экземпляре."""
    if held is None or not held.url:
        return
    original = session.request

    def request(*args, **kwargs):
        used = held.url
        method = args[0] if args else kwargs.get("method", "")
        read_only = str(method).upper() in {"GET", "HEAD", "OPTIONS"}
        try:
            response = original(*args, **kwargs)
        except Exception as exc:
            if humanize.is_network(exc):
                report_fail(used, exc)
                if read_only and held.url == used and not _stays(held) and held.swap():
                    print(f"[proxy] сбой сети через {short(used)} — "
                          f"дальше через {short(held.url)}")
                if read_only:
                    session.proxies = {"all": _remote_dns(held.url)}
            raise
        report_ok(used)
        return response

    session.request = request


def wait_usable(stop=None, timeout: float = WAIT_SEC, task: str = None) -> bool:
    """Ждать, пока оживёт хоть один прокси. True — есть живой (или прокси
    выключили), False — не дождались за timeout или stop() сказал хватит.
    Мёртвые проверяются по ходу не чаще WAIT_RECHECK."""
    global _wait_said
    deadline = time.monotonic() + timeout
    with _lock:
        say = time.monotonic() - _wait_said > 60
        if say:
            _wait_said = time.monotonic()
    if say:
        eventlog.say("все прокси не отвечают — ждём до %d мин" % (timeout // 60),
                     "warn", source="proxy")
    while True:
        urls = configured(task)
        if not urls or _usable(urls):
            return True
        if (stop and stop()) or time.monotonic() >= deadline:
            return False
        due = _claim(urls, WAIT_RECHECK)
        if due:
            check_all(due)
            continue
        time.sleep(1)


# --- фоновая перепроверка мёртвых -------------------------------------------

def _ensure_watch() -> None:
    global _watch
    with _lock:
        if _watch is not None:
            return
        _watch = threading.Thread(target=_watch_loop, name="proxy-watch", daemon=True)
        _watch.start()


def _watch_loop() -> None:
    """Перепроверять мёртвых, пока они есть в списке. Ожил хоть один — следующий
    круг снова через RECHECK_MIN, иначе пауза растёт до RECHECK_MAX."""
    global _watch
    delay = RECHECK_MIN
    while True:
        time.sleep(delay)
        urls = configured()
        with _lock:
            dead = [u for u in urls if _entry(u)["state"] == "dead"]
            if not dead:
                _watch = None
                return
        # кого только что проверил ждущий воркер — второй раз не трогаем
        due = _claim(dead, RECHECK_MIN / 2)
        if not due:
            continue
        marks = check_all(due)
        revived = any(m["state"] == "ok" for m in marks)
        delay = RECHECK_MIN if revived else min(delay * 2, RECHECK_MAX)


# --- фоновая проверка устаревших --------------------------------------------
#
# Раздел «Прокси» показывает состояние, а не предлагает его узнать кнопкой:
# вердикт становится свежим сам. Цена — соединение через прокси (пинг и один
# GET robots.txt), поэтому платит только тот, кто раздел открыл: поток
# поднимает snapshot, а его зовёт именно этот раздел. Строки в работе
# пропускаются — их вердикт обновляет сама работа (report_ok/report_fail), а
# проверка отняла бы у аккаунта соединение и попала бы в его же счёт сбоев.

def _ensure_auto_check() -> None:
    global _auto
    with _lock:
        if _auto is not None:
            return
        _auto = threading.Thread(target=_auto_loop, name="proxy-auto", daemon=True)
        _auto.start()


def _due_for_check() -> list:
    """Строки, за которые фон берётся сам: вердикта нет или он старше
    AUTO_CHECK_SEC, и строка не занята арендой (её вердикт обновляет сама
    работа, а проверка отняла бы у аккаунта соединение). Занимаем их через
    _claim под _lock — следующий круг тех же строк не возьмёт.

    Кнопка «Проверить сейчас» и старт прохода кампании ходят мимо этой
    заявки: им нужен вердикт по каждой строке списка, поэтому строку, которую
    фон проверяет прямо сейчас, они проверят второй раз."""
    return _claim(configured(), AUTO_CHECK_SEC, skip=_busy)


def _auto_loop() -> None:
    """Проверять устаревшие, пока идёт программа: поток демон, останавливать не
    нужно. Первый круг сразу: снимок поднимает поток тогда, когда человек
    открыл раздел, и вердикт нужен ему сейчас, а не через AUTO_CHECK_TICK.
    Списка нет или прокси выключены — configured() пуст, делать нечего."""
    due = []
    while True:
        try:
            due = _due_for_check()
            if due:
                check_all(due)
        except Exception as exc:  # noqa: BLE001 — фон не должен умереть молча
            # свой сбой проверка ловит сама; сюда попадает неожиданное —
            # снимаем заявку, иначе строки залипнут в «проверяю» навсегда
            with _lock:
                _checking.difference_update(due)
            print(f"[proxy] автопроверка сорвалась: {type(exc).__name__}: {exc}")
        time.sleep(AUTO_CHECK_TICK)


# --- для интерфейса ---------------------------------------------------------

def _ui_context() -> dict:
    """Что отметке нужно, кроме состояния строки: тумблер «использовать прокси»
    (выключен — пул сам не проверяет), cooldown смены IP (для rotate_in),
    словарь ссылок смены IP (для разбора строк) и словарь вердиктов страны
    (для country). Одним чтением config на весь снимок: config перечитывает
    файл на каждый get, а под замком пула читать файл нельзя."""
    cfg = config.load()
    links = cfg.get("proxy_rotate_urls")
    countries = cfg.get("proxy_countries")
    rot = cfg.get("proxy_rotation")
    from . import proxies
    def _set(key):
        return {p.strip() for p in (cfg.get(key) or [])
                if isinstance(p, str) and p.strip()}

    return {"enabled": proxies.as_bool(cfg.get("proxy_enabled"), False),
            "cooldown": _cooldown(cfg.get("proxy_rotate_cooldown_sec")),
            "links": links if isinstance(links, dict) else {},
            "countries": countries if isinstance(countries, dict) else {},
            "rotation": rot if isinstance(rot, dict) else {},
            # отметки строк: «годится для входа» и «выключена». Считаются по
            # полной строке — она уникальна даже когда адрес у строк общий
            "login": _set("proxies_login"),
            "publish": _set("proxies_publish"),
            "off": _set("proxies_off")}


_cooldown_said = None    # о каком кривом значении уже сказали в ленте (см. _cooldown)


def _cooldown(value):
    """Секунды паузы между сменами IP из настроек; None — значение не задано,
    умолчание возьмёт proxies.rotate_left.

    Кривое значение («30 сек») не роняет выдачу раздела: раньше int() на нём
    бросал ValueError, и снимок «Прокси» отдавал пустоту, пока настройку не
    поправят вручную. Берём умолчание и говорим об этом в ленте — настройку
    правит человек, а снимок спрашивают часто, поэтому повторяем только про
    то же самое кривое значение. Помним не «сказали ли вообще», а само
    значение: иначе починенная и сломанная заново настройка проходила
    бы молча."""
    global _cooldown_said
    if value is None:
        return None
    from . import proxies
    try:
        float(value)
    except (TypeError, ValueError):
        if _cooldown_said != value:
            _cooldown_said = value
            eventlog.say("пауза между сменами IP в настройках не число — беру 30 с",
                         "warn", source="proxy")
    return proxies.clamp_seconds(value, proxies.DEFAULT_COOLDOWN,
                                 proxies.MAX_ROTATE_COOLDOWN_SEC)


def _next_check_at(url: str, entry: dict, ctx: dict):
    """Когда пул сам возьмётся за строку, unix-секунды; None — не возьмётся:
    прокси выключены, строка в работе (её вердикт обновляет сама работа) или
    проверяется прямо сейчас. Просроченной строке называем «сейчас»: фоновый
    поток забирает её на ближайшем круге. У мёртвой срок бывает раньше — её
    перепроверяет не только этот круг (см. _watch_loop)."""
    if not ctx.get("enabled") or url in _checking or _busy(url):
        return None
    return int(max(time.time(), entry["checked_at"] + AUTO_CHECK_SEC))


def _parsed(url: str, ctx: dict):
    """Разобранная строка прокси для отметки. Разбор и чтение config идут до
    замка пула: снимок на сотню строк иначе держал бы замок на файловых
    чтениях. Нет ключа links в ctx — entry_for прочитает config сам."""
    from . import proxies
    return proxies.entry_for(url, ctx.get("links"))


def _scheme(url: str, entry: dict, parsed):
    """Тип прокси для отметки: названный пользователем в строке или выясненный
    у самого прокси (proxies.detect). None — строку писали без схемы, и прокси
    ещё не отвечал."""
    from . import proxies
    if entry["scheme"]:
        return entry["scheme"]
    if proxies.needs_detect(url):
        return None
    return parsed.scheme if parsed is not None else None


def _mark(url: str, entry: dict, ctx: dict, parsed) -> dict:
    """Отметка для UI; звать под _lock. parsed — уже разобранная строка
    (_parsed), busy — сколько дел сейчас через него, rotating и rotate_in —
    состояние ссылки смены IP, country — вердикт TikTok о стране (см.
    _ui_context, _country_for).

    login/publish — отмечена ли строка для входа/публикации, enabled — не
    выключена ли она. Отметки считает сервер, а не фронт: там они лежат полными строками, а
    на экран полные строки не уходят (в них логин и пароль)."""
    from . import proxies
    link = parsed.rotate_url if parsed is not None else ""
    return {"proxy": short(url),
            "login": url in ctx.get("login", ()),
            "publish": url in ctx.get("publish", ()),
            "enabled": url not in ctx.get("off", ()),
            "state": "checking" if url in _checking else entry["state"],
            "scheme": _scheme(url, entry, parsed),
            "country": entry["country"] or _country_for(_country_key(url, parsed), ctx),
            # как меняет IP (rotation): link/own/static/rotating, None — не мерили
            "rotation": _rotation_record(url, (ctx.get("rotation") or {}).get(_country_key(url, parsed)))
                        .get("kind"),
            "ms": entry["ms"], "ping": entry["ping"], "error": entry["error"],
            # оператор выхода при последней удачной проверке (ipinfo)
            "org": entry["org"] or None,
            "busy": _busy(url),
            "checked_at": int(entry["checked_at"]) or None,
            "next_check_at": _next_check_at(url, entry, ctx),
            "rotating": bool(link),
            "rotate_in": int(proxies.rotate_left(link, ctx.get("cooldown")))
                         if link else 0}


def snapshot(urls) -> list:
    """Отметки по списку в том же порядке. Поднимает фоновую проверку
    устаревших: раздел «Прокси» опрашивает снимок, значит состояние само
    становится свежим у того, кто раздел открыл.

    Строки разбираются до замка — разбору нужен config, а config под общим
    замком пула не читается. urls — любой перебор, включая генератор:
    список снимается один раз в начале, иначе второй проход по нему (за
    отметками) отдал бы пусто."""
    urls = list(urls)
    _ensure_auto_check()
    ctx = _ui_context()
    parsed = {u: _parsed(u, ctx) for u in urls}
    with _lock:
        return [_mark(u, _entry(u), ctx, parsed.get(u)) for u in urls]


def prune(urls) -> None:
    """Список прокси поменяли: состояния удалённых строк забываем."""
    keep = set(urls or [])
    with _lock:
        for url in [u for u in _health if u not in keep]:
            _health.pop(url, None)
    _pulse()
