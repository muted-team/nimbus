# -*- coding: utf-8 -*-
"""Разбор строк прокси и ротация внешнего IP по ссылке провайдера.

Зачем модуль: строку прокси пользователь вставляет как дал провайдер, а дают
её десятком разных способов. Раньше строка уходила в curl_cffi как есть —
`1.2.3.4:8080:user:pass` (самая частая выдача) молча не работала. Здесь она
приводится к одному каноническому виду `scheme://user:pass@host:port`.

Что понимает parse_line:
  http://user:pass@host:port     socks5://user:pass@host:port
  host:port                      host:port:user:pass
  user:pass@host:port            user:pass:host:port
  host:port@user:pass            [2001:db8::1]:8080:user:pass
  socks5 1.2.3.4:1080            HOST;PORT;USER;PASS  (и | , таб как разделители)
Схема без префикса — http. Логин и пароль со спецсимволами (@ : / #) в
канонической форме percent-кодируются, иначе их съест разбор URL. Назвал
пользователь схему или она подставлена, помнит сам разбор (ProxyEntry.named);
у самого прокси тип спрашивает detect() — им пользуется проверка живости
(proxy_pool), когда в строке схемы не было (needs_detect).

Ссылка на ротацию IP живёт в той же строке и НЕ требует ключевого слова:
любой http(s)-адрес, который не является самим прокси, считается ссылкой
ротации. Отличаем по форме — у прокси-эндпоинта нет пути и параметров, у
ротационной ссылки почти всегда есть путь или query:
  socks5://u:p@host:9696 https://api.pro/rotate?key=ab12
  1.2.3.4:8080:u:p  change ip: api.pro/rot?key=ab12
  http://u:p@host:8080 | http://api.pro/reset/ab12

Ротация (rotate): GET по ссылке идёт с прямого IP, а не через сам прокси —
провайдеры привязывают ссылку к ключу или к белому списку и запрос через
прокси отбивают. Ссылка меняет IP на весь порт целиком, поэтому один
rotate_url ротируется строго по одному (лок на ссылку) и не чаще cooldown.
"""
import ipaddress
import re
import socket
import threading
import time
import urllib.parse

# --- разбор -----------------------------------------------------------------

# Схемы, которые понимает libcurl (curl_cffi) и requests+pysocks.
_SCHEMES = {
    "http": "http",
    "https": "https",
    "socks": "socks5",
    "socks4": "socks4",
    "socks4a": "socks4a",
    "socks5": "socks5",
    "socks5h": "socks5h",
    "sock5": "socks5",
    "s5": "socks5",
    "s4": "socks4",
}

# URL со схемой: и прокси-эндпоинт, и ссылка ротации ловятся одним выражением.
_URL_RE = re.compile(
    r"(?i)\b(?P<scheme>https?|socks5h|socks4a|socks[45]|socks|sock5|s[45])://"
    r"(?P<rest>[^\s,;|'\"<>]+)")

# Голая ссылка без схемы: домен с точкой и путём/параметрами —
# «api.pro/rot?key=1». Порт-эндпоинт (host:9696) сюда не попадает: у него
# нет ни '/', ни '?' после хоста.
_BARE_URL_RE = re.compile(
    r"(?i)\b(?P<host>[a-z0-9][a-z0-9.-]*\.[a-z]{2,})(?::(?P<port>\d{1,5}))?"
    r"(?P<tail>[/?][^\s,;|'\"<>]*)")

# Схема отдельным словом перед адресом: «socks5 1.2.3.4:1080».
_SCHEME_WORD_RE = re.compile(
    r"(?i)(?:^|[\s,;|])(https?|socks5h|socks4a|socks[45]|socks|sock5|s[45])"
    r"(?=[\s,;|:]|$)")

_HOST_RE = re.compile(r"(?i)^[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?$")

# Мусор, который приезжает вместе со вставкой из таблицы или мессенджера: BOM
# (U+FEFF), нулевой пробел (U+200B), неразрывный пробел (U+00A0) и два
# разделителя строк — U+2028 и U+2029. Написано escape-последовательностями, а
# не самими знаками, нарочно: невидимые в литерале разделители строк
# splitlines() считает отдельными строками, и в этом файле их выходило на две
# больше, чем видят git и редактор, — ссылки «файл:строка» из реестра на этот
# файл разъезжались.
_JUNK = "\U0000FEFF\U0000200B\U000000A0\U00002028\U00002029"
_QUOTES = "\"'«»“”`"


class ProxyEntry:
    """Один разобранный прокси: канонический адрес + ссылка ротации.

    named — схема названа в самой строке (False — строка была без схемы, и
    разбор подставил http). Знание живёт только здесь: в каноническом адресе,
    который уходит в config, схема уже подставлена, и по нему не отличить
    написанное «http://» от подстановки (см. needs_detect)."""

    __slots__ = ("scheme", "host", "port", "user", "password", "rotate_url",
                 "raw", "named")

    def __init__(self, scheme, host, port, user="", password="",
                 rotate_url="", raw="", named=True):
        self.scheme = scheme
        self.host = host
        self.port = port
        self.user = user or ""
        self.password = password or ""
        self.rotate_url = rotate_url or ""
        self.raw = raw or ""
        self.named = bool(named)

    @property
    def netloc(self) -> str:
        """host:port — IPv6 в квадратных скобках, как требует URL."""
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{host}:{self.port}"

    @property
    def url(self) -> str:
        """Канонический адрес: то, что уходит в curl_cffi/requests."""
        if self.user or self.password:
            user = _quote_cred(self.user)
            pwd = _quote_cred(self.password)
            return f"{self.scheme}://{user}:{pwd}@{self.netloc}"
        return f"{self.scheme}://{self.netloc}"

    @property
    def safe(self) -> str:
        """Адрес без логина и пароля — для логов и UI."""
        return f"{self.scheme}://{self.netloc}"

    @property
    def line(self) -> str:
        """Строка для textarea: адрес и, если есть, ссылка ротации."""
        return f"{self.url} {self.rotate_url}".strip()

    @property
    def key(self) -> tuple:
        """Ключ дедупликации: один и тот же порт с теми же кредами."""
        return (self.scheme, self.host.lower(), self.port, self.user, self.password)

    def __repr__(self):
        rot = " +rotate" if self.rotate_url else ""
        return f"<ProxyEntry {self.safe}{rot}>"


def _clean(raw: str) -> str:
    """Снять мусор вставки: BOM, неразрывные пробелы, кавычки по краям."""
    text = raw or ""
    for ch in _JUNK:
        text = text.replace(ch, " " if ch != "﻿" else "")
    text = text.strip().strip(_QUOTES).strip()
    # хвостовой комментарий: решётка после пробела (в URL '#' — фрагмент,
    # его не трогаем)
    text = re.split(r"\s+#", text, maxsplit=1)[0].strip()
    return text


def _norm_scheme(word: str) -> str:
    return _SCHEMES.get((word or "").strip().lower(), "")


def _valid_port(value) -> int:
    """Порт числом 1..65535, иначе 0."""
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError):
        return 0
    return port if 1 <= port <= 65535 else 0


def _valid_host(value: str) -> str:
    """Хост: IPv4, IPv6 (в скобках или без) или доменное имя. '' — не хост."""
    host = (value or "").strip()
    if not host:
        return ""
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        pass
    if len(host) > 253:
        return ""
    # односложный хост без точки — почти всегда обрывок разбора; localhost
    # оставляем, им пользуются локальные туннели
    if "." not in host and host.lower() != "localhost":
        return ""
    return host if _HOST_RE.match(host) else ""


def _looks_like_rotation(scheme: str, rest: str) -> bool:
    """URL похож на ссылку ротации, а не на прокси-эндпоинт.

    Прокси-эндпоинт — это голый host:port, без пути и параметров. Всё, у
    чего есть путь длиннее '/' или query, — ссылка провайдера. socks-схема
    ротационной не бывает: такие ссылки всегда http(s)."""
    if scheme.startswith("socks") or scheme in ("s4", "s5", "sock5"):
        return False
    tail = rest.split("@")[-1]
    path = tail.split("/", 1)[1] if "/" in tail else ""
    return bool(path.strip("/")) or "?" in tail


def _split_fields(text: str) -> list:
    """Поля прокси из строки с любым разделителем: ':' ';' '|' ',' пробел."""
    return [p for p in re.split(r"[\s:;|,]+", text.strip()) if p]


# Слова-подписи, которыми провайдер обвешивает строку: «change ip: ссылка»,
# «proxy socks5 ...». Режем их только по краям списка полей и только если
# обычный разбор не сложился.
_NOISE_STRONG = {
    "proxy", "proxies", "ip", "change", "changeip", "rotate", "rotation",
    "reset", "refresh", "link", "url", "type", "new",
    "прокси", "ссылка", "смена", "ротация", "ротации", "адрес",
}
# Эти слова бывают настоящим логином («user», «pass»), поэтому срезаем их,
# только когда без них остаётся полный набор host:port:логин:пароль.
_NOISE_WEAK = {
    "port", "host", "login", "user", "username", "pass", "password", "pwd",
    "логин", "пароль", "порт", "хост",
}


def _strip_noise(fields, words):
    """Срезать слова-подписи по краям списка полей."""
    out = list(fields)
    while out and out[0].lower().strip(".:") in words:
        out.pop(0)
    while out and out[-1].lower().strip(".:") in words:
        out.pop()
    return out


def _quote_cred(value: str) -> str:
    """Логин/пароль для URL. Уже закодированное (%40) второй раз не кодируем."""
    if "%" in value and urllib.parse.unquote(value) != value:
        return value
    return urllib.parse.quote(value, safe="")


def _from_fields(fields, scheme):
    """Позиционный разбор ровно двух или четырёх полей."""
    if len(fields) == 2:
        host, port = _valid_host(fields[0]), _valid_port(fields[1])
        if not host:
            return None, f"«{fields[0]}» не похоже на адрес хоста"
        if not port:
            return None, f"порт «{fields[1]}» вне диапазона 1–65535"
        return ProxyEntry(scheme, host, port), ""
    if len(fields) == 4:
        # host:port:user:pass либо user:pass:host:port — различаем по тому,
        # какое поле похоже на порт
        if _valid_host(fields[0]) and _valid_port(fields[1]):
            return ProxyEntry(scheme, _valid_host(fields[0]),
                              _valid_port(fields[1]), fields[2], fields[3]), ""
        if _valid_host(fields[2]) and _valid_port(fields[3]):
            return ProxyEntry(scheme, _valid_host(fields[2]),
                              _valid_port(fields[3]), fields[0], fields[1]), ""
        return None, "из четырёх полей не складывается host:port:логин:пароль"
    if len(fields) == 3:
        return None, "три поля — не хватает пароля (нужно host:port:логин:пароль)"
    if len(fields) <= 1:
        return None, "нет порта — нужно как минимум host:port"
    return None, f"{len(fields)} полей — не понимаю формат"


def _rescue_fields(fields, scheme):
    """Полей больше четырёх: ищем host:port, остальное считаем логином и
    паролем. Пароль собираем обратно через ':' — двоеточие в пароле частая
    история, и именно оно даёт лишние поля."""
    for i in range(len(fields) - 1):
        host, port = _valid_host(fields[i]), _valid_port(fields[i + 1])
        if not host or not port:
            continue
        after = fields[i + 2:]
        before = fields[:i]
        if len(after) >= 2:
            return ProxyEntry(scheme, host, port, after[0], ":".join(after[1:]))
        if len(before) >= 2:
            return ProxyEntry(scheme, host, port, before[0], ":".join(before[1:]))
        if not after and not before:
            return ProxyEntry(scheme, host, port)
    return None


def _parse_endpoint(text: str, scheme: str):
    """Разбор адреса без схемы: все сырые формы провайдеров.

    Возвращает (ProxyEntry, "") либо (None, "текст ошибки")."""
    text = text.strip().strip(_QUOTES).strip()
    if not text:
        return None, "пустая строка"

    user = password = ""
    host = ""
    port = 0

    if "@" in text:
        left, _, right = text.rpartition("@")
        # обычная форма user:pass@host:port, но встречается и наоборот
        for endpoint, creds in ((right, left), (left, right)):
            fields = _split_fields(endpoint)
            if len(fields) == 2 and _valid_host(fields[0]) and _valid_port(fields[1]):
                host, port = _valid_host(fields[0]), _valid_port(fields[1])
                # логин отделён от пароля ПЕРВЫМ двоеточием: в паролях
                # провайдеров ':' встречается, и резать по всем нельзя
                creds = creds.strip().strip(_QUOTES).strip()
                user, _, password = creds.partition(":")
                break
        else:
            return None, "не вижу host:port ни до, ни после '@'"
        return ProxyEntry(scheme, host, port, user, password), ""

    # IPv6 без '@': [2001:db8::1]:8080[:user:pass]
    if text.startswith("["):
        closing = text.find("]")
        if closing == -1:
            return None, "не закрыта скобка IPv6-адреса"
        host = _valid_host(text[:closing + 1])
        rest = _split_fields(text[closing + 1:])
        if not host or not rest:
            return None, "после IPv6-адреса нет порта"
        port = _valid_port(rest[0])
        if not port:
            return None, f"порт «{rest[0]}» вне диапазона 1–65535"
        if len(rest) == 3:
            user, password = rest[1], rest[2]
        elif len(rest) != 1:
            return None, "не понимаю поля после IPv6-адреса"
        return ProxyEntry(scheme, host, port, user, password), ""

    fields = _split_fields(text)
    entry, err = _from_fields(fields, scheme)
    if entry is not None:
        return entry, ""

    # не сложилось — вторая попытка без слов-подписей провайдера
    cleaned = _strip_noise(fields, _NOISE_STRONG)
    weak = _strip_noise(cleaned, _NOISE_WEAK)
    if len(weak) >= 4:
        cleaned = weak
    if cleaned and cleaned != fields:
        entry, err2 = _from_fields(cleaned, scheme)
        if entry is not None:
            return entry, ""
        err = err2 or err
    if not cleaned:
        cleaned = fields

    if len(cleaned) > 4:
        entry = _rescue_fields(cleaned, scheme)
        if entry is not None:
            return entry, ""
    return None, err


def parse_line(raw: str):
    """Разобрать одну строку. Возвращает (ProxyEntry|None, ошибка|"").

    (None, "") — строку надо пропустить: она пустая или это комментарий."""
    text = _clean(raw)
    if not text or text.startswith("#") or text.startswith("//"):
        return None, ""

    scheme = ""
    endpoint_text = ""
    rotate_url = ""
    leftovers = text

    # 1. URL со схемой: раскладываем на прокси-эндпоинт и ссылку ротации
    for match in _URL_RE.finditer(text):
        got = _norm_scheme(match.group("scheme"))
        rest = match.group("rest")
        if not endpoint_text and not _looks_like_rotation(match.group("scheme"), rest):
            scheme, endpoint_text = got, rest
        elif not rotate_url:
            rotate_url = match.group(0)
        leftovers = leftovers.replace(match.group(0), " ", 1)

    # 2. Ссылка ротации без схемы: «api.pro/rot?key=1»
    if not rotate_url:
        bare = _BARE_URL_RE.search(leftovers)
        if bare:
            rotate_url = "https://" + bare.group(0)
            leftovers = leftovers.replace(bare.group(0), " ", 1)

    # 3. Схема отдельным словом: «socks5 1.2.3.4:1080»
    if not scheme:
        word = _SCHEME_WORD_RE.search(leftovers)
        if word:
            scheme = _norm_scheme(word.group(1))
            leftovers = leftovers.replace(word.group(1), " ", 1)

    # 4. Остаток строки — сам прокси, если его не дал URL со схемой
    if not endpoint_text:
        endpoint_text = leftovers
    entry, err = _parse_endpoint(endpoint_text, scheme or "http")
    if err:
        return None, err

    entry.named = bool(scheme)   # без схемы http подставлен, а не написан
    entry.rotate_url = _normalize_rotate_url(rotate_url)
    entry.raw = text
    return entry, ""


def _normalize_rotate_url(url: str) -> str:
    """Ссылка ротации в пригодный для запроса вид ('' — ссылки нет)."""
    url = (url or "").strip().strip(_QUOTES).strip().rstrip(".,;")
    if not url:
        return ""
    if not re.match(r"(?i)^https?://", url):
        url = "https://" + url
    return url


def parse_text(text: str):
    """Разобрать textarea целиком.

    Возвращает (entries, errors): entries — уникальные ProxyEntry в порядке
    ввода, errors — список {"line": номер, "text": строка, "error": причина}.
    Дубликат порта с теми же кредами отбрасывается молча — при ротации по
    списку он всё равно означал бы два подряд одинаковых IP."""
    entries = []
    errors = []
    seen = set()
    for number, raw in enumerate((text or "").splitlines(), 1):
        entry, err = parse_line(raw)
        if err:
            errors.append({"line": number, "text": _clean(raw), "error": err})
            continue
        if entry is None:
            continue
        if entry.key in seen:
            continue
        seen.add(entry.key)
        _remember(entry)
        entries.append(entry)
    return entries, errors


def parse_list(items):
    """То же для списка строк (пришёл JSON-массив, а не текст)."""
    return parse_text("\n".join(str(x) for x in (items or [])))


# --- тип прокси: названный в строке и определённый работой --------------------
#
# Строку прокси пользователь вставляет как дал провайдер, и схему называет не
# всегда. Без схемы разбор подставляет http — для SOCKS-прокси это неверно, и
# запросы через него не идут. Поэтому «схему называли?» помнит сам разбор:
# в каноническом адресе, который уходит в config, схема уже подставлена, и по
# нему написанное «http://» от подстановки не отличить.

_named_lock = threading.Lock()
_named = {}     # канонический адрес -> названа ли схема в строке пользователя


def _remember(entry) -> None:
    """Запомнить, назвала ли строка схему. Зовётся только на то, что написал
    человек (parse_text): entry_for и пинг разбирают уже канонический адрес, где
    схема подставлена, — запомнить по ним значит стереть знание."""
    with _named_lock:
        _named[entry.url] = entry.named


def scheme_named(url: str):
    """Названа ли схема в строке пользователя: True/False, а None — про этот
    адрес процесс ничего не знает (после перезапуска config хранит только
    канонический вид)."""
    with _named_lock:
        return _named.get(url)


def needs_detect(url: str) -> bool:
    """Спрашивать ли у прокси его тип: строку писали без схемы.

    Про адрес, которого процесс не разбирал (после перезапуска), спрашиваем
    только когда схемы в нём и нет — так выглядит строка, поправленная в
    config.json руками; канонический адрес схему уже несёт, и переспрашивать
    написанное пользователем незачем."""
    named = scheme_named(url)
    if named is not None:
        return not named
    entry, _ = parse_line(url)
    return entry is not None and not entry.named


DETECT_TIMEOUT = 5.0    # ответ прокси на вопрос о типе — как пинг (proxy_pool)
# Куда просит CONNECT вопрос о типе: тот же хост, что у проверки живости
# (proxy_pool.CHECK_URL), — прокси с белым списком узнаёт адрес.
DETECT_TARGET = "www.tiktok.com:443"


def _sock(host: str, port: int, timeout: float):
    """Подключение к самому прокси: сокет или None (адрес не отвечает)."""
    try:
        return socket.create_connection((host, port), timeout=timeout)
    except OSError:
        return None


def _talk(sock, greeting: bytes) -> bytes:
    """Отправить приветствие и забрать ответ — сколько придёт."""
    try:
        sock.sendall(greeting)
        return sock.recv(64)
    except OSError:
        return b""


def _is_http(host: str, port: int, timeout: float) -> bool:
    """HTTP-прокси отвечает на CONNECT строкой «HTTP/…»; 407 на чужой пароль —
    тоже ответ и тоже значит HTTP, поэтому учётные данные не шлём."""
    sock = _sock(host, port, timeout)
    if sock is None:
        return False
    try:
        greeting = ("CONNECT %s HTTP/1.1\r\nHost: %s\r\n\r\n"
                    % (DETECT_TARGET, DETECT_TARGET)).encode()
        return _talk(sock, greeting)[:5].upper() == b"HTTP/"
    finally:
        sock.close()


def _is_socks5(host: str, port: int, timeout: float, creds: bool) -> bool:
    """SOCKS5 здоровается ответом в два байта, первый из которых 0x05 (в том
    числе 0xFF «способ не подошёл» — прокси всё равно SOCKS5). Пароль по сети
    не идёт: в приветствии только перечислены способы входа, которыми мы умеем
    пользоваться."""
    sock = _sock(host, port, timeout)
    if sock is None:
        return False
    try:
        greeting = b"\x05\x02\x00\x02" if creds else b"\x05\x01\x00"
        reply = _talk(sock, greeting)
        return len(reply) >= 2 and reply[0] == 0x05
    finally:
        sock.close()


def detect(host, port, user="", password="", timeout=DETECT_TIMEOUT) -> str:
    """Спросить у самого прокси его тип: "http", "socks5" или "" (промолчал).

    Сначала CONNECT — HTTP-прокси отвечает на него строкой «HTTP/…». Потом
    приветствие SOCKS5. Два подключения, а не одно: на чужое приветствие ответа
    не будет, и ждать его в том же сокете значит сложить два таймаута (так же
    устроен пинг proxy_pool._ping). socks4 не отвечает ни на то, ни на другое —
    для него пусто, и строка остаётся как написана."""
    host = _valid_host(host)
    port = _valid_port(port)
    if not host or not port:
        return ""
    if _is_http(host, port, timeout):
        return "http"
    if _is_socks5(host, port, timeout, bool(user or password)):
        return "socks5"
    return ""


# --- закрепление IP («липкая сессия») -----------------------------------------
#
# Ротирующий шлюз выдаёт новый IP на каждое новое соединение — так было бы и у
# браузера на этой прокси. Явные параметры пользователя не меняем. Для
# NoShadow без них вход формирует отдельный маршрут аккаунта; сам список
# прокси остаётся прежним. Режим закрепления не гарантирует неизменный выход.
_OWN_STICKY = re.compile(r"(?i)(?:^|[-_])(?:session|sessid|sessionid|sid)[-_]")
_NOSHADOW_TIME = re.compile(r"(?i)(?:^|-)time-(\d+)(?:-|$)")
_NOSHADOW_PLAIN = re.compile(r"[A-Za-z0-9_]+(?:-country-[A-Za-z]{2})?", re.I)


def noshadow_session(url: str, session_id: str, minutes: int = 15) -> str:
    """Route for a NoShadow account without explicit provider options.

    Keep supplied session/time (including time=0), unknown options and other
    providers unchanged. The caller persists the ID before any connection;
    this helper never reads configuration or claims a measured stable IP.
    """
    try:
        parsed = urllib.parse.urlsplit(url or "")
        ports = {"http": (6969,), "socks5": (9696, 1080), "socks5h": (9696, 1080)}
        if ((parsed.hostname or "").lower() != "proxy.noshadow.pro"
                or parsed.port not in ports.get(parsed.scheme, ())
                or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
            return url
        user = urllib.parse.unquote(parsed.username or "")
        if not _NOSHADOW_PLAIN.fullmatch(user) or parsed.password is None:
            return url
    except (TypeError, ValueError):
        return url
    if not isinstance(session_id, str) or not re.fullmatch(r"[A-Za-z0-9]{1,64}", session_id):
        raise ValueError("invalid NoShadow session ID")
    if type(minutes) is not int or not 1 <= minutes <= 120:
        raise ValueError("invalid NoShadow session duration")
    # Insert into the raw username only: preserve password encoding, host
    # spelling, country and scheme byte for byte.
    prefix, credentials = url.split("://", 1)
    raw_user, remainder = credentials.split(":", 1)
    return f"{prefix}://{raw_user}-session-{session_id}-time-{minutes}:{remainder}"


def has_own_sticky(url: str) -> bool:
    """Закрепление задано в логине; это режим, не гарантия одного выхода.

    У noshadow session без положительного time ротирует на новом соединении.
    Для других провайдеров сохранены их прежние session/sessid/sid признаки.
    """
    parsed = urllib.parse.urlsplit(url or "")
    user = urllib.parse.unquote(parsed.username or "")
    if (parsed.hostname or "").lower() == "proxy.noshadow.pro":
        minutes = _NOSHADOW_TIME.search(user)
        return bool(minutes and int(minutes[1]) > 0)
    return bool(_OWN_STICKY.search(user))


# socks5:// и socks4:// curl резолвит САМ, нашим локальным DNS, и прокси
# получает уже IP: провайдер видит все имена TikTok, а CDN подбирает узел под
# место нашего резолвера (www.tiktok.com — европейский узел), хотя выход в США.
# socks5h/socks4a отдают имя прокси — резолвит он, как у пользователя там.
_REMOTE_DNS = {"socks5": "socks5h", "socks4": "socks4a"}


def remote_dns(url: str) -> str:
    """Тот же прокси, но имена резолвит он сам, а не наш DNS."""
    scheme, sep, rest = (url or "").partition("://")
    return f"{_REMOTE_DNS.get(scheme.lower(), scheme)}{sep}{rest}" if sep else url


# --- ротация ----------------------------------------------------------------

IP_CHECK_URL = "https://api.ipify.org"
DEFAULT_COOLDOWN = 30.0   # сек между двумя ротациями одной ссылки
DEFAULT_SETTLE = 3.0      # сек ожидания, пока провайдер применит новый IP
_VERIFY_TRIES = 4         # попыток увидеть новый IP после ротации
_VERIFY_PAUSE = 2.0

# Потолок proxy_rotate_cooldown_sec. `rotate()` спит на это число секунд
# ПЕРЕД самой сменой IP (в том же вызове, который ждёт браузер), а клиент
# ждёт весь путь ROTATE_TIMEOUT (web/src/api/proxies.ts) — 240 с. Остаток
# пути без учёта cooldown (см. разбивку в комментарии рядом с ROTATE_TIMEOUT):
# проверка «до» 15 с + три попытки дёрнуть ссылку по 20 с с паузами (80 с) +
# выдержка 3 с + проверка «после» 66 с = 164 с. 240 - 164 = 76 с потолок без
# запаса; берём 60 с — вдвое больше умолчания и с ~16 с запасом на сетевые
# накладные расходы, которых нет в этих цифрах (сами тайм-ауты — уже верхние
# границы, обычно короче).
MAX_ROTATE_COOLDOWN_SEC = 60.0

# Ссылка меняет IP на весь порт: две параллельные ротации одной ссылки
# отберут IP друг у друга, поэтому лок и время последнего вызова — на ссылку.
_rot_guard = threading.Lock()
_rot_locks = {}
_rot_last = {}

# Провайдер отвечает 200 и текстом «слишком часто» — по коду это не поймать.
_TOO_OFTEN_RE = re.compile(
    r"(?i)too\s*(?:frequent|often|many)|rate\s*limit|frequenc|подожд|слишком часто")


def _lock_for(url: str) -> threading.Lock:
    with _rot_guard:
        lock = _rot_locks.get(url)
        if lock is None:
            lock = _rot_locks[url] = threading.Lock()
        return lock


def current_ip(proxy_url: str = "", timeout: float = 15.0) -> str:
    """Внешний IP: через прокси, если он передан, иначе прямой. '' — не узнали."""
    try:
        from curl_cffi import requests
        kwargs = {"timeout": timeout}
        if proxy_url:
            # "all" — форма curl_cffi: одна запись на любую схему
            kwargs["proxies"] = {"all": remote_dns(proxy_url)}
        resp = requests.get(IP_CHECK_URL, **kwargs)
        ip = (resp.text or "").strip()
        return ip if len(ip) <= 45 else ""
    except Exception:  # noqa: BLE001 — проверка IP необязательна, молчим
        return ""


def clamp_seconds(value, default: float, maximum: float = None) -> float:
    """Секунды из значения настройки: число в [0, maximum] или default.

    Как `config.clamp_threads`: значение задаёт человек, и мусор в нём ронять
    вызывающего нечем. Без этого `"30 сек"` в `proxy_rotate_cooldown_sec`
    бросал ValueError прямо в выдаче раздела «Прокси» (proxy_pool._mark →
    rotate_left) и в самой ротации. Отрицательное — тоже кривое, берём default.

    `maximum` — потолок сверху (не задан — сверху не ограничиваем): без него
    огромное число в настройке уходило прямо в `time.sleep` внутри `rotate()`
    (см. MAX_ROTATE_COOLDOWN_SEC) и растягивало серверный путь смены IP дольше
    клиентского таймаута запроса."""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return default
    if seconds < 0:
        return default
    if maximum is not None and seconds > maximum:
        return maximum
    return seconds


# Слова, которыми в config.json пишут «да» и «нет». Настройку правят руками, и
# тумблер приезжает из файла строкой не реже, чем настоящим true/false.
_TRUE_WORDS = {"1", "true", "yes", "on", "да", "вкл", "включено"}
_FALSE_WORDS = {"0", "false", "no", "off", "нет", "выкл", "выключено"}


def as_bool(value, default: bool = True) -> bool:
    """Тумблер из значения настройки: строка его не переворачивает.

    `bool("false")` — истина, поэтому выключенное в config.json строкой
    включалось бы. Понимаем написанное человеком: `false/no/off/0/нет` —
    выключено, `true/yes/on/1/да` — включено, пустое и всё прочее — default
    (умолчание самого ключа). Тот же класс, что у clamp_seconds: значение
    задаёт человек, и падать на нём нечем."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().lower()
    if text in _TRUE_WORDS:
        return True
    if text in _FALSE_WORDS:
        return False
    return default


def _forget_country(entry) -> None:
    """IP только что сменился по ссылке провайдера — прежний вердикт страны
    (proxy_pool.country) был про старый адрес. Дальше страну переспросит
    очередная проверка живости; лениво, чтобы модуль прокси не тянул
    proxy_pool на импорте (тот сам зовёт proxies)."""
    from . import proxy_pool
    proxy_pool.forget_country(entry)


def rotate(entry, cooldown: float = None, settle: float = None,
           verify: bool = True, log=None) -> dict:
    """Сменить внешний IP прокси по ссылке провайдера.

    Возвращает {"ok", "skipped", "changed", "ip_before", "ip_after", "reason"}.
    ok=False означает только «ссылку дёрнуть не удалось» — вызывающий не
    обязан из-за этого пропускать аккаунт: старый IP обычно рабочий."""
    say = log or (lambda *a, **k: None)
    result = {"ok": True, "skipped": True, "changed": False,
              "ip_before": "", "ip_after": "", "reason": ""}
    if entry is None or not getattr(entry, "rotate_url", ""):
        result["reason"] = "ссылка ротации не задана"
        return result

    url = entry.rotate_url
    cooldown = (DEFAULT_COOLDOWN if cooldown is None
                else clamp_seconds(cooldown, DEFAULT_COOLDOWN, MAX_ROTATE_COOLDOWN_SEC))
    settle = (DEFAULT_SETTLE if settle is None
              else clamp_seconds(settle, DEFAULT_SETTLE))
    result["skipped"] = False

    with _lock_for(url):
        waited = cooldown - (time.time() - _rot_last.get(url, 0.0))
        if waited > 0:
            say(f"[proxy] смена IP: ждём {waited:.0f} с — ссылку дёргали только что")
            time.sleep(waited)

        if verify:
            result["ip_before"] = current_ip(entry.url)

        ok, reason = _call_rotate(url, say)
        _rot_last[url] = time.time()
        result["ok"] = ok
        result["reason"] = reason
        if not ok:
            say(f"[proxy] IP не сменён: {reason} — работаем на старом")
            return result

        # ссылка дёрнута успешно — IP на этом порту уже не тот, что раньше,
        # даже если verify=False (не проверяем) или отдал старый IP: прежний
        # вердикт страны про него больше не годится
        _forget_country(entry)

        time.sleep(settle)
        if verify:
            before = result["ip_before"]
            for attempt in range(_VERIFY_TRIES):
                ip = current_ip(entry.url)
                result["ip_after"] = ip or result["ip_after"]
                if ip and (not before or ip != before):
                    result["changed"] = bool(before) and ip != before
                    break
                if attempt < _VERIFY_TRIES - 1:
                    time.sleep(_VERIFY_PAUSE)
            if before and result["ip_after"] and not result["changed"]:
                result["reason"] = "IP не сменился"
                say(f"[proxy] IP не сменился ({before})", level="warn")
            elif result["ip_after"]:
                say(f"[proxy] IP сменён: {before or '?'} → {result['ip_after']}", level="ok")
        else:
            say("[proxy] IP сменён", level="ok")
    return result


def _call_rotate(url: str, say) -> tuple:
    """GET по ссылке ротации с прямого IP. Возвращает (ok, причина).

    Причина — короткая, для ленты событий; ответ провайдера и текст
    исключения — в подробности журнала (print)."""
    from curl_cffi import requests
    from . import humanize
    last = ""
    for attempt in range(3):
        try:
            resp = requests.get(url, timeout=20)
            body = (resp.text or "")[:300].strip()
            if resp.status_code == 429 or _TOO_OFTEN_RE.search(body):
                print(f"[proxy] ссылка смены IP: HTTP {resp.status_code}: {body}")
                last = "провайдер просит подождать"
                say(f"[proxy] {last}, повтор через 10 с", level="warn")
                time.sleep(10)
                continue
            if resp.status_code >= 400:
                print(f"[proxy] ссылка смены IP: HTTP {resp.status_code}: {body}")
                last = f"ссылка смены IP ответила HTTP {resp.status_code}"
                time.sleep(2)
                continue
            return True, body
        except Exception as exc:  # noqa: BLE001 — сеть, повторяем
            print(f"[proxy] ссылка смены IP: {type(exc).__name__}: {exc}")
            last = "ссылка смены IP не открылась — " + humanize.network(exc)
            time.sleep(2)
    return False, last or "не удалось вызвать ссылку"


def rotate_left(url: str, cooldown: float = None) -> float:
    """Секунд до следующей смены IP по этой ссылке (0 — можно сейчас).

    Ждёт не строка, а ссылка: она меняет IP на весь порт целиком, поэтому
    cooldown считается по ссылке (`_rot_last`), и воркеры на одном порту стоят
    в очереди друг за другом (см. rotate). Кривое значение настройки заменяется
    умолчанием (clamp_seconds), а не роняет выдачу."""
    if not url:
        return 0.0
    cooldown = (DEFAULT_COOLDOWN if cooldown is None
                else clamp_seconds(cooldown, DEFAULT_COOLDOWN, MAX_ROTATE_COOLDOWN_SEC))
    return max(0.0, cooldown - (time.time() - _rot_last.get(url, 0.0)))


# --- связь с config ---------------------------------------------------------

def entry_for(proxy_url: str, links=None):
    """ProxyEntry по канонической строке из config.proxies (со ссылкой из
    config.proxy_rotate_urls). None — строка пустая или не разбирается.

    links — уже прочитанный config.proxy_rotate_urls: пул отдаёт один словарь
    на весь снимок (proxy_pool._ui_context), иначе config читался бы с диска на
    каждую строку, да ещё и под общим замком пула."""
    from . import config
    if not proxy_url:
        return None
    entry, err = parse_line(proxy_url)
    if err or entry is None:
        return None
    if not entry.rotate_url:
        links = config.get("proxy_rotate_urls") if links is None else links
        if isinstance(links, dict):
            entry.rotate_url = links.get(entry.url) or links.get(entry.safe) or ""
    return entry


def rotate_for(proxy, log=None) -> dict:
    """Ротация по строке прокси из конфига или по готовому ProxyEntry —
    с настройками (cooldown/settle/verify) из config.

    Все три настройки читаются через зажим (clamp_seconds, as_bool): значение
    задаёт человек, и строка `"false"` выключает проверку, а не включает её."""
    from . import config
    entry = proxy if isinstance(proxy, ProxyEntry) else entry_for(proxy)
    if entry is None or not entry.rotate_url:
        return {"ok": True, "skipped": True, "changed": False,
                "ip_before": "", "ip_after": "",
                "reason": "ссылка ротации не задана"}
    return rotate(entry,
                  cooldown=config.get("proxy_rotate_cooldown_sec"),
                  settle=config.get("proxy_rotate_settle_sec"),
                  verify=as_bool(config.get("proxy_rotate_verify")),
                  log=log)
