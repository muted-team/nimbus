"""Стенд интерфейса: отдаёт ui/ и отвечает на /api/* выдуманными данными.

Нужен, чтобы смотреть и скриншотить все экраны и состояния, не трогая живые
аккаунты, прокси и публикацию. Настоящий сервер (main.py) при старте греет
анонимную сессию через прокси — стенд в сеть не ходит вовсе.

  Run the corresponding check in tests/.
  Run the corresponding check in tests/.
  Run the corresponding check in tests/.

Сценарий меняется на лету, без перезапуска:
  GET /_mock?scenario=running|waiting|done|restored|idle|empty|clean|error
  сценарии: running — идёт публикация, waiting — ждёт следующий круг,
  done — прогон завершён с отчётом, restored — отчёт прошлого запуска (прохода
  сейчас нет, итог поднят с диска после перезапуска программы), idle — прогонов
  не было, empty — нет ни аккаунтов, ни прокси, ни папок, clean — все аккаунты
  со входом и без теней (пустые срезы «Без входа» и «В тени»), error — сервер
  отдаёт ошибки на списки. Незнакомый сценарий не принимается (ответ 400),
  текущий остаётся: опечатка в адресе не роняет стенд. `scenario=` без имени —
  тот же отказ, что и опечатка.

Случай отметок прокси меняется там же:
  GET /_mock?proxies=mixed|empty|dead|checking
  mixed — один проверенный, один мёртвый и два непроверенных (в работу пул
  берёт всех, кроме мёртвого); empty — список пуст при включённом тумблере;
  dead — мёртвы все; checking — идёт проверка. Одним снимком эти случаи не
  видно, поэтому у каждого свой вход; смена сценария сбрасывает прокси на
  mixed. Незнакомое имя отбивается так же, как у сценария.

Смена IP — тем же запросом, что у живого сервера:
  POST /api/proxies/rotate  {"index": N} — {ok, ip_before, ip_after, reason}
  и свежие отметки раздела; нет номера, строки с таким номером или ссылки
  смены IP — 400. У одной строки смена отвечает «IP не сменился», у другой
  ссылка не открылась (ok=False) — видно и эти ответы; вердикт строки после
  смены гаснет и приходит заново, как у живой ручки.

Список аккаунтов принимается тем же ответом, что у живого сервера:
  POST /api/accounts/bulk  {"text": "логин:пароль[:2FA]\\n…"} — {added, errors}
  и updated у уже бывших логинов: что строка у них заменила (ключ "updated" в
  ответе есть только когда перезапись была).
"""
import argparse
import base64
import io
import json
import random
import re
import threading
import time
import urllib.parse
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEDIA_ROOT = "C:\\TikTokWebAPI\\media"
# папки программы стенда: (имя, фото, видео), свежие сверху
MEDIA = [("Осенний дроп", 64, 0), ("Галерея 24.09 18-05", 12, 3), ("Ролики", 0, 9)]

TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".woff2": "font/woff2",
}

REGIONS = ["US", "US", "DE", "GB", "FR", "BR", "PL", "CA"]
NAMES = [
    "mira.kovalenko", "dasha_smile", "leo.parker", "katya.moon", "sunny_vibes22",
    "alex.rivera", "nastya_daily", "olivia.grace", "max.stone", "polina.art",
    "jake_travels", "vera.light", "emma.rose.x", "ivan_films", "sofia.dreams",
    "noah.beats", "lisa_cooks", "timur.fit", "mia.styles", "roman_gaming",
    "chloe.bloom", "artem.photo", "zoe_dance", "kirill.tech", "ava.morning",
    "denis.cars", "lily.pastel", "egor_music", "grace.notes", "yana.travel",
    "ethan.code", "alina_beauty", "lucas.surf", "marina.sea", "oscar.pets",
    "vika_fashion", "henry.books", "ksenia.yoga", "jack.comedy", "ulyana.art",
    "ruby.sparks", "gleb.drive", "stella.nova", "boris_chef", "iris.garden",
    "fedor.hikes", "nina.vintage", "mark_reviews", "elsa.snow", "averylongusername_for_ellipsis_test",
]

STATE = {"scenario": "running", "auth": False, "authed": False}
# сколько «идёт» фоновая чистка постов на стенде
PURGE_SECONDS = 6
LOCK = threading.Lock()
BOOT = str(int(time.time()))

# обновление профилей: пауза между «записью» одного аккаунта — видно,
# что событие приходит по мере дела, а не разом в конце, как modules/profiles
PROFILE_STEP_SECONDS = 0.35
# живой поток: тик короче прежнего sleep(2), чтобы event: profiles не отставал
# от небольших пауз обновления профилей; LOG_TICKS/PING_TICKS подгоняют
# фейковую публикацию и пинг тишины под прежний ритм (было 2 с и 14 с)
STREAM_TICK = 0.3
LOG_TICKS = 7
PING_TICKS = 50

# Сценарии стенда — один список на все входы: смена по /_mock?scenario=… и
# ключ --scenario. Постороннее значение (опечатка, пробел) отбивается на входе,
# а не падает KeyError'ом посреди разбора снимка кампании: тот рвал соединение
# и оставлял стенд в нерабочем сценарии до перезапуска.
SCENARIOS = ("running", "waiting", "done", "restored", "idle", "empty", "clean", "error")
# сценарии без прогона кампании: снимок пустой, как в «idle». «clean» — про
# срезы аккаунтов (все со входом, теней нет), а не про публикацию; «restored»
# тоже без прохода, но с итогом прошлого запуска — его снимок не пустой
NO_RUN = ("idle", "empty", "clean", "error")
# статус снимка по сценарию: завершённый проход — «stopped», как в живом
# campaign.get_status
RUN_STATUS = {"running": "running", "waiting": "waiting"}

# Отметки проверки стенда живут по тем же правилам, что у пула
# (modules/proxy_pool): вердикт старше AUTO_CHECK_SEC — пул берёт строку сам,
# сменить IP по ссылке можно раз в ROTATE_COOLDOWN секунд (modules/proxies).
AUTO_CHECK_SEC = 300
ROTATE_COOLDOWN = 30
# сколько стенд «ждёт провайдера» при смене IP: у живого сервера это до ~45 с
# (cooldown и проверка адреса), но стоять столько перед снимком экрана незачем
ROTATE_SECONDS = 2.0
# Выдуманные внешние адреса строк — ряд 198.51.100.0/24 (TEST-NET-2), заведомо
# не настоящий: стенд показывает смену IP, в сеть не ходит.
FAKE_IP = "198.51.100.%d"

# Строки прокси стенда: разные схемы, у трёх — ссылка смены IP (идёт в строке
# через пробел, как в config.proxies; по пробелу же её и считают). Последняя —
# без схемы и со ссылкой: по ней видно, что тип строки берётся из адреса, а не
# из ссылки. ROTATE_WAIT — сколько секунд строке ждать смены IP на
# момент запуска (0 — можно сразу, 17 — чтобы отсчёт был виден с первого
# взгляда); у строки из ROTATE_STUCK смена отвечает «IP не сменился», как
# провайдер, адрес которому сменить не удалось, а у строки из ROTATE_BROKEN
# ссылка не открылась (ok=False) — так на стенде видно все три ответа панели.
PROXY_LINES = [
    "socks5://user-country-US:pass@proxy.example.net:9696",
    "http://login:secret@198.51.100.24:8080 https://rotate.example.net/change?key=abc",
    "socks5://user-country-DE:pass@proxy2.example.net:9696 https://rotate.example.net/change?key=def",
    "203.0.113.10:3128:login:password https://rotate.example.net/change?key=ghi",
]
ROTATE_WAIT = {1: 0, 2: 17}
ROTATE_STUCK = (2,)
ROTATE_BROKEN = (3,)
# сколько секунд после смены IP строка считается проверяемой: вердикт о прежнем
# адресе погашен, а свежий проверяет фон — так же у живой ручки (main.py
# _api_proxies_rotate отвечает сразу и зовёт proxy_pool.check отдельным потоком)
RECHECK_SECONDS = 3.0
# Случаи отметок прокси: имя -> состояния строк. Одним снимком их не показать —
# поэтому у каждого свой вход (/_mock?proxies=…). «mixed» — как сразу после
# запуска: пул берёт в работу всех, кроме мёртвого (modules/proxy_pool._usable).
# «checking» — проверка всего списка в разгаре, вердикты ещё не вернулись.
# Строка «хватит ли прокси на потоки» у mixed и checking читается одинаково
# («живых прокси 3») — и это не недоделка стенда: пул после берёт в работу
# всех, кроме мёртвых, а «checking» — надпись _mark, пока адрес в _checking,
# значит и проверяемый идёт в работу наравне с непроверенным. Различаются случаи
# строками панели: у mixed вердикты и «в работе N», у checking — «Проверяем…»
# на каждой строке.
PROXY_CASES = {
    "mixed": ("ok", "unknown", "dead", "unknown"),
    "dead": ("dead", "dead", "dead", "dead"),
    "checking": ("checking", "checking", "checking", "dead"),
    "empty": (),
}


def pick_scenario(name) -> str:
    """Известное имя сценария или "" — постороннее значение (опечатка, пробел,
    пустая строка от `scenario=`) не принимается вовсе."""
    name = str(name or "")
    return name if name in SCENARIOS else ""


def pick_proxy_case(name) -> str:
    """Известное имя случая прокси или "" — постороннее значение не принимается
    так же, как у сценария."""
    name = str(name or "")
    return name if name in PROXY_CASES else ""


def query_param(q: dict, name: str, default: str = "") -> str:
    """Значение параметра запроса. Пустой параметр (`scenario=`, голый `scenario`)
    — пустая строка, а не отсутствие параметра: разбор идёт с keep_blank_values,
    и проверка на входе видит его наравне с опечаткой."""
    values = q.get(name) or []
    return str(values[0]) if values else default


def query_int(q: dict, name: str, default: int = 0) -> int:
    """Число из параметра запроса; пустой или неразборчивый — как отсутствующий,
    чтобы посторонний адрес не ронял обработчик."""
    try:
        return int(query_param(q, name) or default)
    except ValueError:
        return default


def _avatar(seed: int) -> str:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return ""
    rnd = random.Random(seed)
    c1 = tuple(rnd.randint(40, 220) for _ in range(3))
    c2 = tuple(rnd.randint(40, 220) for _ in range(3))
    img = Image.new("RGB", (64, 64), c1)
    d = ImageDraw.Draw(img)
    d.ellipse((14, 10, 50, 46), fill=c2)
    d.rectangle((8, 44, 56, 64), fill=c2)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _preview(seed: int, angle: float) -> str:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return ""
    rnd = random.Random(seed)
    w, h = 540, 675
    img = Image.new("RGB", (w, h))
    top = tuple(rnd.randint(60, 200) for _ in range(3))
    bot = tuple(rnd.randint(20, 120) for _ in range(3))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)], fill=tuple(int(top[i] * (1 - t) + bot[i] * t) for i in range(3)))
    for _ in range(6):
        x, y, r = rnd.randint(0, w), rnd.randint(0, h), rnd.randint(30, 120)
        d.ellipse((x - r, y - r, x + r, y + r), outline=(255, 255, 255), width=3)
    img = img.rotate(angle, resample=Image.BICUBIC)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _iso(delta_min: float = 0) -> str:
    return (datetime.now() + timedelta(minutes=delta_min)).isoformat()


def _unix(delta_min: float = 0) -> int:
    """Unix-время в секундах — так его отдаёт настоящий сервер."""
    return int(time.time() + delta_min * 60)


def _no_link(proxy: str) -> str:
    """Строка без ссылки смены IP: она идёт вторым словом, через пробел — так её
    и хранит config.proxies. Разбор адреса идёт по этой части: у ссылки своя
    схема, и по ней о типе прокси судить нельзя."""
    return proxy.split(" ", 1)[0]


def _short(proxy: str) -> str:
    """Адрес без входа и без ссылки смены IP — как отдаёт modules/proxy_pool."""
    tail = _no_link(proxy.split("@")[-1])
    parts = tail.split(":")
    return parts[0] + ":" + parts[1] if len(parts) > 1 else tail


# что известно о прокси в каждом состоянии: пинг до самого адреса, ответ TikTok
# через него, причина отказа, сколько дел идёт разом (занятый строкой прокси пул
# не проверяет — как и арендованный) и сколько минут назад проверяли (None —
# ещё не проверяли)
HEALTH_DETAIL = {
    "ok": {"ping": 84, "ms": 1240, "error": None, "busy": 3, "checked_ago": 2},
    "dead": {"ping": None, "ms": None, "error": "таймаут соединения 20 с", "busy": 0, "checked_ago": 2},
    "checking": {"ping": None, "ms": None, "error": None, "busy": 1, "checked_ago": 9},
    "unknown": {"ping": None, "ms": None, "error": None, "busy": 0, "checked_ago": None},
}


def _checked_at(state: str):
    """Когда строку проверяли: минуты из HEALTH_DETAIL назад; None — не проверяли."""
    ago = HEALTH_DETAIL[state]["checked_ago"]
    return _unix(-ago) if ago is not None else None


def proxy_scheme(proxy: str):
    """Тип прокси для отметки: схема, названная в адресе, либо None — строку
    писали без схемы, и прокси ещё не отвечал (так же решает
    modules/proxy_pool._scheme).

    Схема берётся из адреса без ссылки смены IP: у ссылки схема своя
    (`https://`), и по всей строке тип выходил мусором — у
    «203.0.113.10:3128:login:password https://rotate…» вместо None уезжало
    «203.0.113.10:3128:login:password https»."""
    head = _no_link(proxy)
    return head.split("://")[0] if "://" in head else None


def _country(proxy: str):
    """Страна строки для стенда: код из логина вида user-country-US, иначе None."""
    m = re.search(r"country-([A-Z]{2})", proxy)
    return m.group(1) if m else None

def health_row(proxy: str, state: str, checked_at, *, enabled: bool = True,
               login: bool = False, publish: bool = False,
               rotate_in: int = 0) -> dict:
    """Отметка прокси для интерфейса — тем же набором полей и типов, что отдаёт
    modules/proxy_pool._mark: checked_at и next_check_at целым числом (эпоха
    секунд) или None, scheme строкой или None, rotating булевым, rotate_in
    секундами. checked_at — когда строку проверяли, enabled — тумблер
    «использовать прокси».

    next_check_at — по тем же правилам, что _next_check_at: у выключенных прокси,
    у проверяемой и у занятой работой строки его нет (там вердикт обновляет сама
    работа)."""
    d = HEALTH_DETAIL[state]
    link = " " in proxy
    return {"proxy": _short(proxy), "state": state, "scheme": proxy_scheme(proxy),
            "login": login, "publish": publish, "enabled": enabled,
            "ms": d["ms"], "ping": d["ping"], "error": d["error"], "busy": d["busy"],
            "checked_at": checked_at,
            "next_check_at": (None if not enabled or state == "checking" or d["busy"]
                              else int(max(time.time(), (checked_at or 0) + AUTO_CHECK_SEC))),
            "rotating": link, "rotate_in": rotate_in if link else 0,
            "country": _country(proxy) if d["ping"] else None}


def account_line(line: str):
    """Аккаунт из строки вставки — тем же набором полей, что пишет живой разбор
    (modules/accounts._parse_account_line): логин и пароль по порядку, дальше
    2FA-секрет. None — строку не разобрать: пустая или в ней одна часть."""
    parts = [p for p in line.strip().split(":") if p]
    if len(parts) < 2:
        return None
    fields = {"username": parts[0], "password": parts[1]}
    if len(parts) > 2:
        fields["totp_secret"] = parts[2].upper()
    return fields


class Data:
    """Выдуманное состояние программы; сценарий задаёт, что в нём лежит."""

    def __init__(self):
        # номер изменения профилей — растёт монотонно, сброс сценария его не
        # трогает (как _change_seq в modules/profiles, только не по времени:
        # тут важен только рост, не абсолютное значение)
        self.profile_seq = 0
        # строки прокси, их вердикты и время проверки — до первого сценария
        self.proxies, self.proxy_state, self.checked_at = [], [], []
        self.proxy_login, self.proxy_publish, self.proxy_off = set(), set(), set()
        self.reset("running")

    def reset(self, scenario: str):
        """Сценарий задаёт, что лежит в выдуманном состоянии. Имя уже проверено
        (pick_scenario) — сюда постороннее значение не доходит."""
        self.scenario = scenario
        empty = scenario == "empty"
        # «чисто»: вход есть у всех и теней ни у кого — пустые срезы «Без входа»
        # и «В тени» показывают, что чинить нечего
        clean = scenario == "clean"
        rnd = random.Random(7)
        self.accounts = []
        self.avatars = {}
        # что вставка уже записала аккаунту (логин, пароль, 2FA-секрет — поля
        # живого разбора): по ним считается перезапись в ответе
        # POST /api/accounts/bulk, и у заведённых стендом аккаунтов они есть —
        # иначе повторная строка ничего не заменяла бы. В морду это не уходит:
        # там секретов нет и у живого сервера.
        self.creds = {}
        # числа из центра автора: приходят только на аккаунты со входом, и
        # нарочно не совпадают с профилем — по ним видно, чьи числа показаны
        self.counters = {}
        if not empty:
            for i, name in enumerate(NAMES):
                has_session = clean or i % 7 != 3
                has_totp = i % 3 != 2
                profile = None
                if i % 9 != 5:
                    profile = {
                        "nickname": name.replace(".", " ").title(),
                        "verified": i % 11 == 4,
                        "private_account": i % 13 == 7,
                        "followers": rnd.choice([0, 12, 340, 1250, 18400, 263000, 2100000]),
                        "likes": rnd.choice([0, 88, 5400, 91000, 1300000]),
                        "posts": {"count": rnd.randint(0, 140), "views": rnd.choice([0, 950, 48000, 3200000]),
                                  "shadow": 0 if clean else (None if i % 4 == 0 else rnd.choice([0, 0, 1, 3]))},
                        # разброс от минут до месяца: видно все виды «Обновлён»
                        "fetched_at": _unix(-rnd.choice([0.5, 8, 90, 600, 4000, 40000])),
                    }
                self.accounts.append({
                    "username": name, "has_session": has_session,
                    "has_totp": has_totp, "has_email": i % 3 == 2 or i % 5 == 0,
                    "avatar": _unix(-60 * (i % 9)) if i % 6 != 1 else None,
                    "profile": profile,
                    # страна — из кук сессии, как у живого: без входа её нет
                    "region": REGIONS[i % len(REGIONS)] if has_session else None,
                    "lang": None,
                })
                self.creds[name] = {"password": "pass%d" % i,
                                    **({"totp_secret": "JBSWY3DPEHPK3PXP"} if has_totp else {})}
                if has_session:
                    self.counters[name] = {
                        "posts": rnd.randint(0, 140),
                        "private_posts": rnd.choice([0, 1, 6]),
                        "followers": rnd.choice([0, 18, 420, 1900, 26000, 320000, 2400000]),
                        # ноль у части аккаунтов: метка о посетителях тогда молчит
                        "unread_visitors": rnd.choice([0, 0, 2, 7, 41, 380]),
                    }
                if i % 6 != 1:
                    self.avatars[name] = _avatar(i)
        self.banned = [] if empty else [
            {"username": "banned.user%d" % i, "banned_at": _unix(-60 * i * 9),
             "ban_reason": "аккаунта нет (1011)" if i % 2 else "вход: аккаунт заблокирован"}
            for i in range(1, 6)
        ]
        # Сценарий «empty» — прокси не заводили вовсе: пустого списка и
        # выключенного тумблера хватает. Список пуст при ВКЛЮЧЁННОМ тумблере —
        # свой случай (/_mock?proxies=empty): за выключенным расчёт уходит в
        # «прокси выключены» и до «списка нет» не доходит.
        self.set_proxy_case("empty" if empty else "mixed", enabled=not empty)
        self.settings = {"browser_profile": "firefox155", "browser_profile_active": "firefox155",
                         "browser_profiles": ["chrome152", "firefox155"],
                         "threads": 5, "threads_max": 1000, "server_wait_min": 30,
                         "server_wait_max": 240, "port": 8740, "host": "0.0.0.0",
                         "bound": {"host": "0.0.0.0", "port": 8740},
                         "phone": {"on": True, "active": True,
                                   "links": ["http://192.168.1.10:8740"]},
                         "password": {"available": True, "set": True, "min_len": 4},
                         "server": {"url": "https://78.153.139.65",
                                    "default": "https://78.153.139.65", "custom": False}}
        # username -> когда запросили чистку постов (фоновая, с итогом)
        self.purges = {}
        # обновление профилей (POST /api/profiles/refresh), как modules/profiles:
        # seq растёт монотонно и переживает сброс сценария, чтобы открытая
        # страница не приняла старый снимок за новый
        self.profile_state = {"running": False, "total": 0, "done": 0, "ok": 0,
                              "current": [], "pending": [], "failed": [], "error": None,
                              "started_at": None, "finished_at": None}
        self.profile_changed = {}  # username -> seq последнего изменения профиля
        self.uniq = {
            "enabled": True,
            "rotate": {"enabled": True, "locked": False, "min": -10, "max": 10},
            "scale": {"enabled": True, "locked": False, "min": 0, "max": 20},
            "compress": {"enabled": True, "locked": True, "min": 80, "max": 90},
            "brightness": {"enabled": True, "locked": True, "min": -5, "max": 5},
            "contrast": {"enabled": False, "locked": True, "min": -5, "max": 5},
            "saturation": {"enabled": True, "locked": False, "min": -5, "max": 5},
            "gamma": {"enabled": False, "locked": True, "min": -5, "max": 5},
            "hue": {"enabled": True, "locked": True, "min": -20, "max": 20},
            "limits": {"rotate": [-360, 360], "scale": [0, 100], "compress": [1, 100],
                       "brightness": [-100, 100], "contrast": [-100, 100], "saturation": [-100, 100],
                       "gamma": [-100, 100], "hue": [-180, 180]},
        }
        self.form = {} if empty else {
            "posts_per_account": 6, "creatives": "copies", "keep_photos": False,
            "delete_before": -2, "slots": ["C:\\slots\\1", MEDIA_ROOT + "\\Осенний дроп", "D:\\photos\\very\\long\\path\\to\\folder\\slot3"],
            "video_slots": ["C:\\video"], "media": "photo",
            "caption": "Новая коллекция уже здесь #fashion #style #fyp", "title": "Осенний дроп",
            "min_delay_ms": 1500, "max_delay_ms": 4000,
            "repeat": scenario == "waiting", "repeat_unit": "hour", "repeat_min": 2, "repeat_max": 4,
        }
        self.posts_tick = 0
        self.logs = []
        self.seq = 0
        if not empty:
            self._seed_logs()

    def set_proxy_case(self, case: str, enabled: bool = True):
        """Случай отметок прокси: живой список, пустой, все мертвы, идёт
        проверка. Задаётся сценарием при сбросе и отдельным входом
        (`/_mock?proxies=…`) — иначе случаи не развести. Имя уже проверено
        (pick_proxy_case), постороннее сюда не доходит."""
        states = PROXY_CASES[case]
        self.proxies_enabled = enabled
        self.set_lines(PROXY_LINES[:len(states)], states, initial=True)
        self.proxy_login = set(self.proxies[::2])
        self.proxy_publish = set(self.proxies[1::2])
        if self.proxies:
            # первая строка намеренно годится для обоих дел: группы могут пересекаться
            self.proxy_publish.add(self.proxies[0])
        self.proxy_off = set()

    def set_lines(self, lines, states=None, initial: bool = False):
        """Список строк прокси поменяли. states — вердикты строк по порядку, когда
        их называет случай стенда; без них вердикты строк с теми же адресами
        остаются, а новые строки приходят непроверенными. initial — список завёл
        сам стенд (тогда работают ROTATE_WAIT, ROTATE_STUCK и ROTATE_BROKEN);
        список, пришедший от PUT, чужой и свежий — ждать смены IP не надо
        никому."""
        if states is None:
            known = {_short(p): (s, at)
                     for p, s, at in zip(self.proxies, self.proxy_state, self.checked_at)}
            pairs = [known.get(_short(p), ("unknown", None)) for p in lines]
        else:
            pairs = [(s, _checked_at(s)) for s in states]
        self.proxies = list(lines)
        self.seed_rotations(initial=initial)
        self.proxy_state = [s for s, _ in pairs]
        self.checked_at = [at for _, at in pairs]

    def seed_rotations(self, initial: bool = True):
        """Отсчёт до смены IP строки — от отметки последней смены (rot_last), а
        не числом в снимке: иначе каждый свежий снимок начинал бы отсчёт заново,
        и он разошёлся бы с тем, что делает кнопка."""
        now = time.time()
        self.rot_last = {}
        self.rot_stuck = set()
        self.rot_broken = set()
        self.rot_ips = {}
        # строки, у которых вердикт перепроверяется после смены IP: адрес под
        # ними сменился, и прежний вердикт был про другой (см. row)
        self.recheck = {}
        for i, p in enumerate(self.proxies):
            if " " not in p:
                continue
            wait = ROTATE_WAIT.get(i, 0) if initial else 0
            self.rot_last[p] = now - (ROTATE_COOLDOWN - wait)
            if initial and i in ROTATE_STUCK:
                self.rot_stuck.add(p)
            if initial and i in ROTATE_BROKEN:
                self.rot_broken.add(p)

    def health_rows(self) -> list:
        """Отметки всех строк на текущий момент: вердикт и время проверки стенд
        помнит, а срок следующей проверки и отсчёт до смены IP считаются заново
        на каждый снимок — как у пула (proxy_pool.snapshot зовёт _mark)."""
        return [self.row(i, p, s, at)
                for i, (p, s, at) in enumerate(zip(self.proxies, self.proxy_state,
                                                  self.checked_at))]

    def row(self, i: int, proxy: str, state: str, checked_at) -> dict:
        """Отметка строки: отсчёт до смены IP берём от последней смены, а вердикт
        после смены IP — свежий: старый гаснет (он был про прежний адрес), и
        проверка идёт заново. Пока она идёт, строка «проверяется» — как _checking
        у пула; время последней проверки при этом остаётся прежним (так его и
        отдаёт _mark). Стенд в сеть не ходит: через RECHECK_SECONDS вердикт
        встаёт на место сам."""
        until = self.recheck.get(proxy)
        if until is not None:
            if time.time() < until:
                state = "checking"
            else:
                # адрес сменился, ссылка открылась — вердикт свежий, и время
                # проверки у него своё (момент, когда проверка закончилась)
                state, checked_at = "ok", int(until)
                self.proxy_state[i] = state
                self.checked_at[i] = checked_at
                del self.recheck[proxy]
        left = 0.0
        if " " in proxy:
            left = ROTATE_COOLDOWN - (time.time() - self.rot_last.get(proxy, 0.0))
        return health_row(proxy, state, checked_at,
                          enabled=proxy not in self.proxy_off,
                          login=proxy in self.proxy_login,
                          publish=proxy in self.proxy_publish,
                          rotate_in=int(max(0.0, left)))

    def _seed_logs(self):
        samples = [
            ("ok", "mira.kovalenko", "пост 3 опубликован"),
            ("", "dasha_smile", "вход выполнен"),
            ("warn", "leo.parker", "прокси не ответил, пересадка на следующий"),
            ("err", "katya.moon", "вход не удался: неверный пароль"),
            ("ok", "", "публикация запущена: 50 аккаунтов, по 6 постов"),
            ("", "sunny_vibes22", "очистка прошлых постов: удалено 6"),
            ("ok", "alex.rivera", "пост 1 опубликован"),
            ("err", "banned.user1", "аккаунт забанен и отключён"),
        ]
        for i in range(40):
            level, acc, text = samples[i % len(samples)]
            self.add_log(level, acc, text, ts=time.time() - (40 - i) * 17)
        for i in range(20):
            self.add_log("", "", "POST https://www.tiktok.com/api/v1/item/create — 200 за 812 мс",
                         ts=time.time() - (20 - i) * 31, debug=True, source="publish")

    def add_log(self, level, account, text, ts=None, debug=False, source=""):
        self.seq += 1
        self.logs.append({"seq": self.seq, "ts": ts or time.time(), "level": level, "account": account,
                          "text": text, "debug": debug, "source": source})
        del self.logs[:-600]

    def profile_status(self) -> dict:
        """GET /api/profiles/refresh — снимок хода, как modules/profiles.status()."""
        st = dict(self.profile_state)
        st["seq"] = self.profile_seq
        return st

    def profile_touch(self, name: str = "") -> None:
        """Поменялся аккаунт name или ход обновления — растит seq, как
        modules/profiles._touch."""
        self.profile_seq += 1
        if name:
            self.profile_changed[name] = self.profile_seq

    def profile_changes(self, since: int) -> dict:
        """Всё, что поменялось после seq since — для event: profiles на живом
        потоке, тем же набором полей, что modules/profiles.changes(): seq,
        status, profiles (username -> объект профиля или None) и avatars
        (стенд аватарки в потоке не шлёт — пустой словарь)."""
        names = [n for n, seq in self.profile_changed.items() if seq > since]
        found = {}
        for n in names:
            acc = next((a for a in self.accounts if a["username"] == n), None)
            found[n] = acc["profile"] if acc else None
        return {"seq": self.profile_seq, "status": self.profile_status(),
                "profiles": found, "avatars": {}}

    def profile_start(self, usernames) -> dict:
        """POST /api/profiles/refresh — фоном «обновить» профили, как
        modules/profiles.start(): уже идущее обновление получает новые имена в
        очередь вместо отказа."""
        names = [str(u).lstrip("@") for u in
                (usernames if usernames is not None else [a["username"] for a in self.accounts])
                if str(u).strip()]
        if self.profile_state["running"]:
            fresh = [n for n in names if n not in self.profile_state["pending"]]
            self.profile_state["pending"].extend(fresh)
            self.profile_state["total"] += len(fresh)
            self.profile_touch()
            return self.profile_status()
        self.profile_state.update(running=True, total=len(names), done=0, ok=0,
                                  current=[], pending=list(names), failed=[], error=None,
                                  started_at=_unix(), finished_at=None)
        self.profile_touch()
        threading.Thread(target=_profile_refresh_worker, daemon=True,
                         name="mock-profile-refresh").start()
        return self.profile_status()

    def campaign(self) -> dict:
        """Снимок кампании. Сценарий «restored» — отчёт прошлого запуска: прохода
        сейчас нет, итог поднят с диска, и про это говорит поле restored (так его
        и ставит campaign._lift_saved_report)."""
        sc = self.scenario
        names = [a["username"] for a in self.accounts]
        base = {"status": "idle", "accounts_total": 0, "accounts_done": 0, "queued": [],
                "posts_per_account": 6, "threads": 5, "workers": [], "results": [],
                "stop_reason": None, "started_at": None, "finished_at": None,
                "updated_at": _iso(), "stop_requested": False, "abort_reason": None,
                "restored": sc == "restored",
                "repeat": False, "media": "photo", "round": 0, "rounds_done": 0, "next_run_at": None}
        # прогона не было: снимок пустой, пуст и отчёт. Он той же формы, что у
        # живого campaign._report — четыре категории и счёт снятых постов
        if sc in NO_RUN or not names:
            base.update(posts_total=0, posts_done=0, posts_failed=0, posts_removed=0,
                        report={"published": [], "failed": [], "banned": [], "removed": [],
                                "posts": 0, "posts_removed": 0})
            return base
        # сколько аккаунтов уже пройдено: в «running» — часть (растёт с каждым
        # тиком живого потока), дальше — все
        done_n = (14 + self.posts_tick // 6) if sc == "running" else len(names)
        done_n = min(done_n, len(names))
        results = []
        # снятые за нарушение правил посты: уведомления читаются перед заливкой,
        # поэтому поле есть у дошедших до публикации; у сорвавшихся на входе и у
        # забаненных — ноль, как в живом campaign._worker_run
        for i, u in enumerate(names[:done_n]):
            if i % 11 == 4:
                results.append({"account": u, "ok": False, "posts_done": 0, "posts_lost": 6,
                                "reason": "вход не удался: капча", "banned": False, "removed": 0})
            elif i % 17 == 8:
                results.append({"account": u, "ok": False, "posts_done": 0, "posts_lost": 6,
                                "reason": "аккаунта нет", "banned": True, "removed": 0})
            else:
                results.append({"account": u, "ok": True, "posts_done": 6 if i % 5 else 4,
                                "posts_lost": 0 if i % 5 else 2, "banned": False,
                                "reason": None if i % 5 else "пост отклонён",
                                "removed": [0, 0, 7, 0, 3][i % 5]})
        workers = []
        if sc == "running":
            # шаги те же, что ставит живой campaign._worker_set: смена IP, вход,
            # уведомления, очистка постов, публикация, ожидание прокси
            steps = ["rotate", "login", "notices", "cleanup", "publishing", "wait_proxy"]
            for k, u in enumerate(names[done_n:done_n + len(steps)]):
                workers.append({"account": u, "step": steps[k],
                                "posts_done": (self.posts_tick + k) % 6, "updated": _iso()})
        report = {"published": [r["account"] for r in results if r["posts_done"]],
                  "failed": [r["account"] for r in results if not r["posts_done"] and not r["banned"]],
                  "banned": [r["account"] for r in results if r["banned"]],
                  "removed": [r["account"] for r in results if r["removed"]],
                  "posts": sum(r["posts_done"] for r in results),
                  "posts_removed": sum(r["removed"] for r in results)}
        st = dict(base)
        # статус: у поднятого отчёта прохода сейчас нет, и статус остаётся idle,
        # как после campaign._lift_saved_report; у завершённого прохода — stopped
        st.update(
            status=RUN_STATUS.get(sc, "idle" if sc == "restored" else "stopped"),
            accounts_total=len(names), accounts_done=done_n, queued=names, workers=workers,
            results=results, started_at=_iso(-47),
            finished_at=_iso(-3) if sc != "running" else None,
            stop_reason="все аккаунты пройдены" if sc in ("done", "restored") else None,
            repeat=sc == "waiting", round=3 if sc == "waiting" else 0, rounds_done=2 if sc == "waiting" else 0,
            next_run_at=_iso(135) if sc == "waiting" else None,
        )
        st["posts_total"] = len(names) * 6
        st["posts_done"] = report["posts"] + sum(w["posts_done"] for w in workers)
        st["posts_failed"] = sum(r["posts_lost"] for r in results)
        st["posts_removed"] = report["posts_removed"]
        st["report"] = report
        return st


DATA = Data()
UI_DIR = ROOT / "ui"


def _profile_refresh_worker() -> None:
    """Поток стенда для POST /api/profiles/refresh: «пишет» аккаунты по одному
    с паузой (PROFILE_STEP_SECONDS) — как modules/profiles._run_thread, только
    без сети. Каждая запись растит DATA.profile_seq — event: profiles на живом
    потоке видит рост и свежую строку по мере дела, а не разом в конце.
    Читает DATA.profile_state["pending"] заново на каждом шаге: имена,
    докинутые вторым нажатием (DATA.profile_start пока идёт этот прогон),
    попадают туда же и уходят следующим шагом."""
    rnd = random.Random()
    while True:
        with LOCK:
            pending = DATA.profile_state["pending"]
            name = pending[0] if pending else None
            if name:
                DATA.profile_state["current"].append(name)
        if name is None:
            break
        time.sleep(PROFILE_STEP_SECONDS)
        with LOCK:
            acc = next((a for a in DATA.accounts if a["username"] == name), None)
            if acc is not None:
                profile = dict(acc.get("profile") or {"nickname": name})
                profile["followers"] = rnd.choice([0, 12, 340, 1250, 18400, 263000, 2100000])
                profile["fetched_at"] = _unix()
                acc["profile"] = profile
            if name in DATA.profile_state["current"]:
                DATA.profile_state["current"].remove(name)
            if name in DATA.profile_state["pending"]:
                DATA.profile_state["pending"].remove(name)
            DATA.profile_state["done"] += 1
            DATA.profile_state["ok"] += 1
            DATA.profile_touch(name)
    with LOCK:
        DATA.profile_state.update(running=False, current=[], finished_at=_unix())
        DATA.profile_touch()

def media_files(name: str) -> list:
    """Файлы папки стенда: столько фото и видео, сколько у неё в MEDIA."""
    ph, v = next(((p_, v_) for n, p_, v_ in MEDIA if n == name), (0, 0))
    now = int(time.time())
    return ([{"file": "IMG_%04d.HEIC" % (4000 + i), "kind": "photo", "size": 2_400_000,
              "mtime": now - i * 60} for i in range(ph)]
            + [{"file": "IMG_%04d.MOV" % (5000 + i), "kind": "video", "size": 48_000_000,
                "mtime": now - (ph + i) * 60} for i in range(v)])


def _thumb(seed: str) -> bytes:
    """Превью фото стенда: та же картинка, что у уникализатора, по имени файла."""
    data = _preview(sum(map(ord, seed)), 0)
    return base64.b64decode(data.split(",", 1)[1]) if data else b""


def media_payload() -> dict:
    return {"root": MEDIA_ROOT, "folders": [
        {"name": n, "path": MEDIA_ROOT + "\\" + n, "photos": ph, "videos": v,
         "mtime": int(time.time()) - i * 3600,
         "preview": [{"file": f["file"], "mtime": f["mtime"]} for f in media_files(n)
                     if f["kind"] == "photo"][:4]}
        for i, (n, ph, v) in enumerate(MEDIA)]}


LICENSE = {"key": "…07fb", "status": "active", "balance": 5239.5, "currency": "₽",
           "name": "demo.user", "expires_at": None}


def license_history() -> list:
    """Транзакции «Профиля»: сегодня, вчера и позавчера, удачные и нет — как
    их отдаёт журнал сервера (server/billing.py history)."""
    now = time.time()
    rows = [
        (0.05, "publish_photo", "Пост с фото", "fixture.account01", True, ""),
        (0.06, "upload_photo", "Загрузка фото", "fixture.account01", True, ""),
        (0.30, "session_check", "Проверка входа", "fixture.account01", True, ""),
        (0.9, "publish_video", "Пост с видео", "fixture.account02", False,
         "10224: Слишком много попыток, попробуйте позже"),
        (1.4, "profiles", "Профили без входа", "u1, u2, u3 +9", True, ""),
        (26, "login", "Вход", "fixture.account03", True, ""),
        (27, "delete", "Удаление постов", "fixture.account03", True, ""),
        (50, "login", "Вход", "fixture.account04", False, "неверный пароль"),
    ]
    out = [{"at": int(now - h * 3600), "action": a, "title": t, "account": acc, "note": "",
            "kind": "debit", "ok": ok, "amount": 0.0, "error": err}
           for h, a, t, acc, ok, err in rows]
    # движения баланса у Muted: пополнение и покупка в другом сервисе
    out += [{"at": int(now - h * 3600), "action": a, "title": t, "account": "", "note": note,
             "kind": kind, "ok": True, "amount": amount, "error": ""}
            for h, a, t, note, kind, amount in (
                (0.5, "topup", "Пополнение", "CryptoPay", "credit", 500.0),
                (30, "purchase", "Покупка", "Muted Shop: аккаунты TikTok ×10", "debit", 350.5))]
    return sorted(out, key=lambda r: r["at"], reverse=True)


def changelog_payload() -> dict:
    """История и версия — из того же CHANGELOG.md, что у живого сервера."""
    import sys
    sys.path.insert(0, str(ROOT))
    from modules import changelog
    return changelog.load()


class Handler(BaseHTTPRequestHandler):
    server_version = "UIMock/1.0"

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            return json.loads(raw or b"{}")
        except ValueError:
            return {}

    def _path(self):
        return urllib.parse.urlparse(self.path)

    def _gate(self, path) -> bool:
        if STATE["auth"] and not STATE["authed"] and path.startswith("/api") and not path.startswith("/api/auth"):
            self._json({"error": "нужен пароль", "auth": True}, 401)
            return False
        return True

    def _proxies_payload(self, **extra) -> dict:
        """Ответ раздела «Прокси» — тем же набором полей, что GET /api/proxies
        (и что main.py._proxies_payload). Лишние поля — только в ответе PUT."""
        return {"proxies": DATA.proxies, "enabled": DATA.proxies_enabled,
                "rotating": sum(1 for p in DATA.proxies if " " in p),
                "health": DATA.health_rows(), **extra}

    def _rotate(self, body):
        """POST /api/proxies/rotate — сменить IP строки списка, как настоящий
        сервер (main.py: ручка `_api_proxies_rotate`): body {"index": N}, ответ
        {ok, ip_before, ip_after, reason} плюс свежие отметки раздела; 400 — нет
        номера, строки с таким номером или ссылки смены IP. В сеть стенд не
        ходит: адреса выдуманные, а ждём ROTATE_SECONDS — у живого провайдера
        смена тоже не мгновенная. Остаток cooldown не отсиживаем: на экране
        кнопка в это время выключена, и ждать столько стенду незачем (живой
        сервер на этот путь тратит cooldown, см. modules/proxies.rotate).

        Три ответа, как у живого провайдера: адрес сменился, «IP не сменился»
        (строки ROTATE_STUCK) и «ссылка не открылась» — ok=False, адреса после
        смены нет (ROTATE_BROKEN, modules/proxies._call_rotate). Снимок раздела
        собирается под замком, как остальные: отметки он считает и меняет."""
        index = body.get("index")
        if not isinstance(index, int) or isinstance(index, bool):
            return self._json({"error": "нужен номер строки: {\"index\": N}"}, 400)
        if not 0 <= index < len(DATA.proxies):
            return self._json({"error": "в списке нет строки прокси с номером %d" % index}, 400)
        proxy = DATA.proxies[index]
        if " " not in proxy:
            return self._json({"error": "у этого прокси нет ссылки смены IP"}, 400)
        time.sleep(ROTATE_SECONDS)
        with LOCK:
            before = FAKE_IP % DATA.rot_ips.get(proxy, 10)
            ok = True
            if proxy in DATA.rot_broken:
                # ссылку дёрнуть не удалось: адреса после смены нет вовсе, и это
                # не «не сменился» — так отвечает _call_rotate при отказе сети
                after, reason, ok = "", "ссылка смены IP не открылась — таймаут соединения", False
            elif proxy in DATA.rot_stuck:
                # проверить новый адрес провайдеру не удалось — так и отвечаем
                # (modules/proxies.rotate: ok=True, причина «IP не сменился»)
                after, reason = before, "IP не сменился"
            else:
                DATA.rot_ips[proxy] = DATA.rot_ips.get(proxy, 10) + 1
                after, reason = FAKE_IP % DATA.rot_ips[proxy], ""
            # ссылку дёрнули — с этого мига идёт cooldown, как _rot_last у пула
            DATA.rot_last[proxy] = time.time()
            payload = self._proxies_payload()
            payload.update(ok=ok, ip_before=before, ip_after=after, reason=reason)
            # ответ собран по прежним вердиктам, а дальше строка перепроверяется:
            # живая ручка гасит вердикт и зовёт proxy_pool.check уже после ответа
            DATA.recheck[proxy] = time.time() + RECHECK_SECONDS
        return self._json(payload)

    def do_GET(self):
        u = self._path()
        path = u.path
        # keep_blank_values: без него разбор молча выбрасывает `scenario=` и
        # голый `scenario`, и пустое имя проходит мимо проверки наравне с верным
        q = urllib.parse.parse_qs(u.query, keep_blank_values=True)
        if path == "/_mock":
            refuse = None
            with LOCK:
                # Сначала проверить оба имени, потом менять состояние: незнакомое
                # имя — отказ, а не исключение, и текущее состояние остаётся как
                # было, следующий запрос обрабатывается как обычно.
                sc = pick_scenario(query_param(q, "scenario")) if "scenario" in q else None
                case = pick_proxy_case(query_param(q, "proxies")) if "proxies" in q else None
                if "scenario" in q and not sc:
                    refuse = ("сценарий не назван" if not query_param(q, "scenario")
                              else "нет такого сценария: %s" % query_param(q, "scenario")[:40])
                elif "proxies" in q and not case:
                    refuse = ("случай прокси не назван" if not query_param(q, "proxies")
                              else "нет такого случая прокси: %s" % query_param(q, "proxies")[:40])
                else:
                    if sc:
                        DATA.reset(sc)
                    if case:
                        DATA.set_proxy_case(case)
                    if query_param(q, "auth"):
                        # пустой `auth=` состояние не меняет: это «не сказано», а
                        # не «выключить пароль»
                        STATE["auth"] = query_param(q, "auth") == "1"
                        STATE["authed"] = False
                current, auth = DATA.scenario, STATE["auth"]
            if refuse is not None:
                return self._json({"error": refuse, "scenarios": list(SCENARIOS),
                                   "proxy_cases": list(PROXY_CASES),
                                   "scenario": current}, 400)
            return self._json({"scenario": current, "auth": auth})
        if not path.startswith("/api"):
            return self._static(path)
        if not self._gate(path):
            return
        if DATA.scenario == "error" and path in ("/api/accounts", "/api/proxies", "/api/settings"):
            return self._json({"error": "внутренняя ошибка сервера"}, 500)
        with LOCK:
            if path == "/api/auth":
                return self._json({"required": STATE["auth"], "ok": STATE["authed"] or not STATE["auth"]})
            if path == "/api/accounts":
                return self._json({"accounts": DATA.accounts, "default_account": None, "banned": DATA.banned})
            if path == "/api/accounts/secrets":
                username = query_param(q, "username")
                if not username:
                    return self._json({"error": "нужен username"}, 400)
                if username not in DATA.creds:
                    return self._json({"error": "нет такого аккаунта: %s" % username[:40]}, 404)
                return self._json({k: v for k, v in DATA.creds[username].items()
                                   if k != "username"})
            if path == "/api/avatars":
                return self._json({"avatars": DATA.avatars})
            if path == "/api/studio/counters":
                # числа студии: только у аккаунтов со входом, у остальных их нет
                return self._json({"counters": DATA.counters})
            if path == "/api/proxies":
                return self._json(self._proxies_payload())
            if path == "/api/settings":
                return self._json(DATA.settings)
            if path == "/api/changelog":
                return self._json(changelog_payload())
            if path == "/api/media":
                return self._json(media_payload())
            if path == "/api/media/files":
                return self._json({"files": media_files(query_param(q, "name") or "")})
            if path == "/api/media/thumb":
                data = _thumb(query_param(q, "file") or "")
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if path == "/api/server/check":
                return self._json({"ok": True, "ms": 48})
            if path == "/api/license":
                return self._json(LICENSE)
            if path == "/api/license/history":
                return self._json({"items": license_history(), "next": None})
            if path == "/api/uniq":
                return self._json(DATA.uniq)
            if path == "/api/campaign/status":
                return self._json(DATA.campaign())
            if path == "/api/campaign/form":
                return self._json(DATA.form)
            if path == "/api/profiles/refresh":
                return self._json(DATA.profile_status())
            if path == "/api/accounts/purge":
                # чистка «идёт» PURGE_SECONDS секунд с момента запроса, потом
                # отдаёт итог — как настоящий сервер (у одного аккаунта ошибка,
                # чтобы было видно, как морда её показывает)
                now = time.time()
                current = sorted(u for u, at in DATA.purges.items()
                                 if now - at < PURGE_SECONDS)
                results = {}
                for user, at in list(DATA.purges.items()):
                    if now - at >= PURGE_SECONDS:
                        results[user] = ({"error": "прокси не отвечает"}
                                         if user.endswith("2") else
                                         {"deleted": 12, "total": 12})
                return self._json({"running": len(current), "current": current,
                                   "results": results})
            if path == "/api/logs":
                after = query_int(q, "after")
                debug = query_param(q, "debug") == "1"
                items = [x for x in DATA.logs if x["seq"] > after and (debug or not x["debug"])]
                return self._json({"items": items[-300:], "seq": DATA.seq})
        if path == "/api/stream":
            return self._stream(q)
        self._json({"error": "нет такого метода: " + path}, 404)

    def _stream(self, q):
        after = query_int(q, "after")
        debug = query_param(q, "debug") == "1"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        def send(event, data):
            chunk = ("event: %s\n" % event if event else "") + "data: " + json.dumps(data, ensure_ascii=False) + "\n\n"
            self.wfile.write(chunk.encode())
            self.wfile.flush()

        try:
            self.wfile.write(("event: hello\ndata: %s\n\n" % BOOT).encode())
            with LOCK:
                send("campaign", DATA.campaign())
                items = [x for x in DATA.logs if x["seq"] > after and (debug or not x["debug"])]
                # номер последнего отправленного изменения профилей — только ход
                # обновления, строки поток берёт по разнице (как profiles_seq в
                # main.py._api_stream)
                profiles_seq = DATA.profile_status()["seq"]
            if items:
                send(None, items[-300:])
            last = DATA.seq
            n = 0
            while True:
                time.sleep(STREAM_TICK)
                n += 1
                with LOCK:
                    if n % LOG_TICKS == 0 and DATA.scenario == "running" and DATA.accounts:
                        DATA.posts_tick += 1
                        acc = NAMES[(14 + DATA.posts_tick) % len(NAMES)]
                        DATA.add_log("ok" if DATA.posts_tick % 4 else "warn", acc,
                                     "пост %d опубликован" % (DATA.posts_tick % 6 + 1) if DATA.posts_tick % 4
                                     else "прокси медленно отвечает, ждём")
                        send("campaign", DATA.campaign())
                    profiles_chunk = DATA.profile_changes(profiles_seq)
                    items = [x for x in DATA.logs if x["seq"] > last and (debug or not x["debug"])]
                    last = DATA.seq
                if profiles_chunk["seq"] != profiles_seq:
                    profiles_seq = profiles_chunk["seq"]
                    send("profiles", profiles_chunk)
                if items:
                    send(None, items)
                elif n % PING_TICKS == 0:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionError, OSError):
            return

    def do_PUT(self):
        path = self._path().path
        if not self._gate(path):
            return
        body = self._body()
        with LOCK:
            if path == "/api/proxies":
                errors = []
                if DATA.scenario == "running" and "text" in body:
                    return self._json({"error": "нельзя менять прокси во время публикации"}, 409)
                if "text" in body:
                    good = []
                    for i, line in enumerate(body["text"].splitlines(), 1):
                        line = line.strip()
                        if not line:
                            continue
                        if ":" in line:
                            good.append(line)
                        else:
                            errors.append({"line": i, "error": "не понял формат: нужен host:port"})
                    DATA.set_lines(good)
                if "enabled" in body:
                    DATA.proxies_enabled = bool(body["enabled"])
                for field, attr in (("login", "proxy_login"),
                                    ("publish", "proxy_publish"),
                                    ("off", "proxy_off")):
                    if field in body:
                        indexes = body[field] if isinstance(body[field], list) else []
                        setattr(DATA, attr, {DATA.proxies[i] for i in indexes
                                            if isinstance(i, int) and not isinstance(i, bool)
                                            and 0 <= i < len(DATA.proxies)})
                return self._json(self._proxies_payload(errors=errors))
            if path == "/api/settings":
                if "browser_profile" in body and body["browser_profile"] not in DATA.settings["browser_profiles"]:
                    return self._json({"error": "неподдерживаемый профиль браузера"}, 400)
                for k in ("threads", "port", "host", "browser_profile"):
                    if k in body:
                        DATA.settings[k] = body[k]
                return self._json(DATA.settings)
            if path == "/api/uniq":
                for k, v in body.items():
                    if isinstance(v, dict) and k in DATA.uniq:
                        DATA.uniq[k].update(v)
                    elif k == "enabled":
                        DATA.uniq["enabled"] = bool(v)
                return self._json(DATA.uniq)
            if path == "/api/campaign/form":
                DATA.form.update(body)
                return self._json(DATA.form)
        self._json({"error": "нет такого метода"}, 404)

    def do_POST(self):
        path = self._path().path
        # Тело читаем один раз, до всех развилок: rfile — поток соединения, и
        # второе чтение уже прочитанных байт ждёт данных, которых не будет —
        # запрос остаётся без ответа. Мимо чтения не проходит ни один
        # POST, иначе неразобранное тело сдвигает границы следующего запроса.
        body = self._body()
        if path == "/api/auth":
            if body.get("password") == "1234":
                STATE["authed"] = True
                return self._json({"ok": True})
            return self._json({"error": "неверный пароль"}, 401)
        if path == "/api/auth/logout":
            STATE["authed"] = False
            return self._json({"ok": True})
        if not self._gate(path):
            return
        if path == "/api/login":
            time.sleep(1.5)
            name = body.get("username")
            with LOCK:
                for a in DATA.accounts:
                    if a["username"] == name:
                        a["has_session"] = True
                DATA.add_log("ok", name, "вход выполнен")
            return self._json({"ok": True, "username": name})
        if path == "/api/proxies/rotate":
            return self._rotate(body)
        with LOCK:
            if path == "/api/accounts/update":
                username, patch = body.get("username"), body.get("patch")
                if not isinstance(username, str) or not username or not isinstance(patch, dict):
                    return self._json({"error": "нужны username и patch"}, 400)
                account = next((a for a in DATA.accounts if a["username"] == username), None)
                if account is None or username not in DATA.creds:
                    return self._json({"error": "нет такого аккаунта: %s" % username[:40]}, 404)
                if any(patch.get(k) == "" for k in ("username", "password")):
                    return self._json({"error": "логин и пароль снять нельзя"}, 400)
                new_name = patch.get("username") or username
                if new_name != username and new_name in DATA.creds:
                    return self._json({"error": "логин %s уже занят" % new_name[:40]}, 400)
                creds = dict(DATA.creds.pop(username))
                for k, v in patch.items():
                    if k == "username":
                        continue
                    if v == "":
                        creds.pop(k, None)
                    else:
                        creds[k] = v
                DATA.creds[new_name] = creds
                for store in (DATA.avatars, DATA.counters):
                    if username in store:
                        store[new_name] = store.pop(username)
                account.update(username=new_name, has_totp="totp_secret" in creds,
                               has_email="email" in creds)
                return self._json(account)
            if path == "/api/accounts/bulk":
                # как modules/accounts.add_accounts_bulk: уже бывший логин не
                # дубль, а перезапись — он уходит в "updated" с перечнем
                # заменённых полей, и ключа "updated" в ответе нет, когда
                # перезаписей не было
                added, updated, errors = [], [], []
                for i, line in enumerate(body.get("text", "").splitlines(), 1):
                    fields = account_line(line)
                    if fields is None:
                        if line.strip():
                            errors.append({"line": i, "reason": "не понял формат строки"})
                        continue
                    username = fields["username"]
                    account = next((a for a in DATA.accounts if a["username"] == username), None)
                    old = DATA.creds.get(username)
                    if account is None or old is None:
                        DATA.accounts.append({"username": username, "has_session": False,
                                              "has_totp": "totp_secret" in fields, "has_email": False,
                                              "avatar": None, "profile": None,
                                              "region": None, "lang": None})
                        DATA.creds[username] = dict(fields)
                        added.append(username)
                        continue
                    # поля, которых в строке нет, у аккаунта остаются и заменой
                    # не считаются — заменённые перечисляем по строке
                    replaced = sorted(k for k, v in fields.items()
                                      if k != "username" and old.get(k) != v)
                    DATA.creds[username] = {**old, **{k: v for k, v in fields.items() if k != "username"}}
                    account["has_totp"] = "totp_secret" in DATA.creds[username]
                    updated.append({"username": username, "replaced": replaced})
                result = {"added": added, "updated": updated, "errors": errors}
                if not updated:
                    del result["updated"]
                return self._json(result)
            if path == "/api/accounts/delete":
                DATA.accounts = [a for a in DATA.accounts if a["username"] != body.get("username")]
                return self._json({"ok": True})
            if path == "/api/accounts/restore":
                DATA.banned = [b for b in DATA.banned if b["username"] != body.get("username")]
                return self._json({"ok": True})
            if path == "/api/accounts/disable":
                usernames = body.get("usernames")
                if usernames is None:
                    single = body.get("username")
                    usernames = [single] if single else []
                disabled, missing = [], []
                for username in usernames:
                    account = next((a for a in DATA.accounts if a["username"] == username), None)
                    if account is None:
                        missing.append(username)
                        continue
                    DATA.accounts = [a for a in DATA.accounts if a["username"] != username]
                    DATA.banned.append({"username": username, "banned_at": _unix(),
                                        "ban_reason": "отключён вручную"})
                    disabled.append(username)
                return self._json({"ok": True, "disabled": disabled, "missing": missing})
            if path == "/api/accounts/purge":
                DATA.purges[body.get("username") or "?"] = time.time()
                return self._json({"ok": True}, 202)
            if path == "/api/proxies/check":
                # как настоящий сервер: пустой список проверять нечего
                if not DATA.proxies:
                    return self._json({"error": "список прокси пуст"}, 400)
                # проверка снимает «идёт проверка»: у непроверенных и
                # проверяемых появляется вердикт и время проверки
                at = _unix()
                for i, s in enumerate(DATA.proxy_state):
                    if s in ("checking", "unknown"):
                        DATA.proxy_state[i] = "ok"
                        DATA.checked_at[i] = at
                return self._json(self._proxies_payload())
            if path == "/api/slots":
                items = []
                lib = {m["path"]: m for m in media_payload()["folders"]}
                for i, f in enumerate(body.get("folders", [])):
                    if f in lib:
                        items.append({"path": f, "exists": True, "photos": lib[f]["photos"],
                                      "videos": lib[f]["videos"]})
                        continue
                    items.append({"path": f, "exists": "very" not in f, "photos": [48, 12, 0][i % 3], "videos": 7})
                return self._json({"items": items})
            if path == "/api/media":
                name = (body.get("name") or "").strip() or body.get("default") or "Папка"
                MEDIA.insert(0, (name, 0, 0))
                return self._json(media_payload()["folders"][0])
            if path in ("/api/media/clear", "/api/media/delete"):
                i = next((k for k, m in enumerate(MEDIA) if m[0] == body.get("name")), None)
                if i is None:
                    return self._json({"error": "папки «%s» нет" % body.get("name")}, 400)
                if path.endswith("clear"):
                    removed = MEDIA[i][1] + MEDIA[i][2]
                    MEDIA[i] = (MEDIA[i][0], 0, 0)
                    return self._json({"ok": True, "removed": removed})
                MEDIA.pop(i)
                return self._json({"ok": True})
            if path == "/api/uniq/preview":
                items = []
                for i, f in enumerate(body.get("folders", [])):
                    angle = random.uniform(-10, 10)
                    items.append({"image": _preview(i + 1, angle), "name": "IMG_20%02d.jpg" % (i + 10),
                                  "applied": {"rotate": angle, "scale": 7.35, "compress": 86,
                                              "brightness": -2.85, "saturation": 1.5, "hue": 12},
                                  "bytes": 284000 + i * 51000,
                                  "meta": {"Размер": "1080×1350", "Формат": "JPEG", "Качество": "86"}})
                return self._json({"items": items})
            if path == "/api/campaign/start":
                DATA.scenario = "running"
                DATA.posts_tick = 0
                return self._json({"ok": True, "status": DATA.campaign()})
            if path == "/api/campaign/stop":
                DATA.scenario = "done"
                return self._json(DATA.campaign())
            if path == "/api/profiles/refresh":
                return self._json(DATA.profile_start(body.get("usernames")))
            if path == "/api/logs/clear":
                DATA.logs = []
                return self._json({"ok": True})
        if path == "/api/slots/upload":
            return self._json({"ok": True, "photos": 49, "videos": 7})
        self._json({"error": "нет такого метода"}, 404)

    def _static(self, path):
        if path == "/":
            path = "/index.html"
        full = (UI_DIR / urllib.parse.unquote(path.lstrip("/"))).resolve()
        if not full.is_relative_to(UI_DIR.resolve()) or not full.is_file():
            return self._json({"error": "не найдено"}, 404)
        data = full.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", TYPES.get(full.suffix.lower(), "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def main():
    global UI_DIR
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--ui", default=str(ROOT / "ui"))
    ap.add_argument("--scenario", default="running", choices=SCENARIOS)
    ap.add_argument("--auth", action="store_true")
    args = ap.parse_args()
    UI_DIR = Path(args.ui)
    STATE["auth"] = args.auth
    DATA.reset(args.scenario)
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    httpd.daemon_threads = True
    print("стенд: http://127.0.0.1:%d  ui=%s  сценарий=%s" % (args.port, UI_DIR, args.scenario), flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
