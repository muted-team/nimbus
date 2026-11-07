"""Local client settings and atomic persistence."""
import json
import os
import re
import threading
import time
from pathlib import Path

from . import paths

ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = ROOT / "config.json"

DEFAULTS = {
    # chrome152 / firefox155; фиксируется при запуске процесса.
    "browser_profile": "firefox155",
    # None, а не конкретный username: чужой дефолт не должен уезжать
    # пользователям в exe. Пустой дефолт -> login.load_account(None) даёт
    # внятную ошибку «добавьте аккаунт и войдите», а session_manager.
    # session_file(None) уходит в общий JSON-файл cookies в корне.
    "default_account": None,
    "host": "0.0.0.0",
    # интерфейс с телефона: программа слушает сеть, а не только этот
    # компьютер, и пускает по паролю (modules/auth.py). Без пароля не
    # включается. Применяется при следующем запуске (app.py)
    "phone_access": False,
    "port": 8740,
    # сколько дел делать одновременно — ОДНО число на всю программу: проверка
    # профилей, вход «во все», проход кампании. Раньше у каждого раздела было
    # своё (константа в profiles, поле в форме публикации), и они разъезжались.
    # Читать только через threads(): там зажим в 1..THREADS_MAX.
    "threads": 5,
    # прокси умер посреди публикации: "swap" — пересесть на другой живой,
    # "stop" — остановить поток вместе с прокси (proxy_pool.reseat)
    "proxy_on_death": "swap",
    # сколько минут ждать наш сервер, когда он перегружен (503), прежде чем
    # сдаться: на наплыве лучше дождаться очереди, чем пропустить аккаунт.
    # Читать только через server_wait_min(): там зажим в 1..SERVER_WAIT_MAX.
    "server_wait_min": 30,
    # как часто фоново обновлять профили аккаунтов, минут. Читать только через
    # clamp_refresh_minutes(): там зажим в 5..REFRESH_MINUTES_MAX.
    "profile_refresh_minutes": 60,
    "proxy": None,
    "proxies": [],
    # явные группы; пустая группа запрещает соответствующее действие, чтобы
    # пул не подставил случайный IP из общего списка
    "proxies_login": [],
    "proxies_publish": [],
    # выключенные строки: лежат в proxies, но в работу не идут ни одним делом.
    # Отдельным списком, а не удалением из proxies, чтобы строка не терялась:
    # выключил на время — она осталась на месте со своим вердиктом и страной.
    "proxies_off": [],
    # тумблер «использовать прокси»: выключен -> и кампания, и ручной вход
    # идут с прямого IP, список proxies/proxy не трогаем.
    "proxy_enabled": True,
    # отметка «схему в строке называли»: {адрес прокси без логина и пароля:
    # да/нет}. Заводит её main.py в том же config.update, что и сам список.
    # Знание «схему здесь не называли» живёт в памяти того процесса, который
    # строку разбирал (modules/proxies.py): в proxies лежит канонический
    # адрес, по которому подставленный http от написанного не отличить.
    # Отметка его возвращает — после перезапуска тип такой строки снова
    # определяется работой, а не догадкой. Секретов в ней нет: логин и пароль
    # в адрес не входят.
    "proxy_scheme_named": {},
    # страна каждой прокси по вердикту самого TikTok: {ключ прокси: {"code",
    # "at"}}. Ключ считает modules/proxy_pool._country_key — адрес без учётки
    # плюс её необратимый отпечаток: у одного шлюза бывает несколько строк, и
    # выходной IP (а с ним и страна) у каждой свой. Секретов здесь нет.
    # Переспрашивается по давности и при смене IP; пусто -> ещё не узнавали.
    "proxy_countries": {},
    # как прокси меняет IP и подобранное закрепление: {ключ: {"kind", ...}}
    # (proxy_pool.rotation), только для показа. Секретов нет.
    "proxy_rotation": {},
    # ключ пользователя к нашему серверу (modules/remote.py) — секрет, как и
    # весь config.json; в интерфейсе видны только последние 4 знака
    "license_key": "",
    # адрес нашего сервера, если он не встроенный (modules/remote.py API_BASE):
    # переехал сервер — пользователь меняет адрес в «Настройках» сам
    "server_url": "",
    # ссылки смены IP: {канонический прокси: ссылка провайдера}. Заполняет
    # разбор строк прокси (modules/proxies.py) — ссылку пишут в той же
    # строке, что и сам прокси. Пусто -> ротацию по ссылке не зовём.
    "proxy_rotate_urls": {},
    # сек между двумя вызовами ОДНОЙ ссылки: провайдеры лимитируют частоту
    "proxy_rotate_cooldown_sec": 30,
    # сек ожидания после вызова — пока провайдер применит новый IP
    "proxy_rotate_settle_sec": 3,
    # проверять смену IP через api.ipify.org (два коротких запроса через
    # прокси); false -> дёргаем ссылку вслепую и идём дальше
    "proxy_rotate_verify": True,
    "paths": {
        # относительные — считаются от корня проекта
        "photos_dir": "assets",
        "jar": "tiktok_cookies.json",
        "ts_guard_config": "ts_guard_config.json",
    },
    "flags": {
        "posts_per_account": 6,
    },
    # Muted Code — сервис кодов подтверждения из почты и TOTP (modules/mailcode.py).
    # base — без хвостового слэша; ключа сейчас нет (auth пустой).
    "mailcode": {
        "base": "https://muted.top",
        "auth": "",
    },
    # последняя заполненная форма публикации (UI подставляет при старте,
    # обновляет при каждом запуске — переживёт смену браузера/приватный
    # режим, в отличие от localStorage). Числа потоков здесь нет: оно общее
    # на всю программу (ключ "threads" выше).
    "campaign_form": {
        "posts_per_account": 6,   # «постов на аккаунт»
        "slots": [],              # папки-слоты
    },
    # уникализатор фото перед заливом (modules/uniq.py)
    "uniq": {
        "enabled": True,
        "rotate": {"enabled": False, "locked": False, "min": 0, "max": 0},
    },
}

_SECRET_KEY_RE = re.compile(
    r"(?i)(password|passwd|secret|token|cookie|session|key|sign)")

# сериализация read-merge-write в update() между потоками (см. доку там)
_write_lock = threading.Lock()


def _merge(base: dict, override: dict) -> dict:
    """Глубокое слияние: override выигрывает; недостающие ключи — из base."""
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


# Кеш разобранного конфига по отпечатку файла. Файл перечитывается, когда
# отпечаток (путь, mtime_ns, размер) сменился: правка руками или другим процессом
# подхватывается сразу, как и раньше. Собственные записи (write_text_atomic в
# config.json) кеш сбрасывают и поднимают _cache_gen — чтение, начатое до записи,
# не успеет положить в кеш старое.
_cache_lock = threading.Lock()
_cache_key = None      # (путь, mtime_ns, размер) разобранного файла
_cache_text = None     # слитый с дефолтами конфиг как JSON-текст
_cache_gen = 0
# Файл, тронутый совсем недавно, в кеш не кладём: часы файловой системы грубее
# наносекунд, и две правки подряд в один «тик» с тем же размером дали бы тот же
# отпечаток. Через секунду отпечаток надёжен.
_CACHE_SETTLE_NS = 1_000_000_000


def _drop_cache() -> None:
    global _cache_key, _cache_text, _cache_gen
    with _cache_lock:
        _cache_key = _cache_text = None
        _cache_gen += 1


def _cached_copy(key):
    """Копия кеша, если он сделан для этого отпечатка; иначе None."""
    with _cache_lock:
        text = _cache_text if _cache_key == key else None
    # каждый вызов получает СВОЙ объект: конфиг правят на месте (update, разборы
    # прокси), общий словарь поломал бы чтение соседних потоков. Разбор готового
    # текста быстрее глубокой копии.
    return None if text is None else json.loads(text)


def load() -> dict:
    """Текущий конфиг. Файл читается заново, когда он изменился (см. кеш выше).
    Нет файла — создаёт. Каждый вызов возвращает новый объект."""
    global _cache_key, _cache_text
    target = paths.here(CONFIG_FILE)
    try:
        st = target.stat()
        key = (str(target), st.st_mtime_ns, st.st_size)
    except OSError:
        st = key = None
    if key is not None:
        hit = _cached_copy(key)
        if hit is not None:
            return hit
    with _cache_lock:
        gen = _cache_gen
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = None
    # _merge отдаёт вложенные значения дефолтов тем же объектом: прогоняем через
    # текст, чтобы правка результата не доходила до DEFAULTS
    text = json.dumps(_merge(DEFAULTS, raw if isinstance(raw, dict) else {}),
                      ensure_ascii=False)
    cfg = json.loads(text)
    if (key is not None and isinstance(raw, dict)
            and time.time_ns() - st.st_mtime_ns > _CACHE_SETTLE_NS):
        with _cache_lock:
            if gen == _cache_gen:
                _cache_key, _cache_text = key, text
    if not target.exists():
        # первое обращение: фиксируем дефолты, чтобы их можно было править
        try:
            save(cfg)
        except OSError:
            pass  # корень недоступен на запись — работаем на дефолтах
    return cfg


def write_text_atomic(path, text: str, *, retries: int = 10,
                      on_error: str = "raise") -> None:
    """Записать файл целиком и атомарно (см. _write_text_atomic).

    Запись в config.json заодно сбрасывает кеш load(): пишет он и этот помощник
    напрямую (save, update), и любой чужой вызов с путём конфига."""
    try:
        _write_text_atomic(path, text, retries=retries, on_error=on_error)
    finally:
        if Path(path) == paths.here(CONFIG_FILE):
            _drop_cache()


def _write_text_atomic(path, text: str, *, retries: int, on_error: str) -> None:
    """Записать файл целиком и атомарно: временный рядом + подмена одним движением.

    Один приём на всю программу: `config.save`, запись accounts.json/banned.json
    (accounts._write_json) и отчёт прохода (campaign._save_report) повторяли его
    каждый по-своему. Оборванная запись (выключили сервер, кончился диск) иначе
    оставляла полфайла, а читатель видел битый JSON — для config.json это
    дефолты без прокси и пароля, для accounts.json потерянный вход.

    На Windows подмена отказывает, пока файл в этот миг читает другой поток
    (open() не даёт FILE_SHARE_DELETE) — до `retries` коротких повторов, и только
    потом решение по `on_error`:
      "raise"  — убрать временный файл и поднять OSError: как рассказать о сбое,
                 решает вызывающий (accounts.json, отчёт прохода);
      "direct" — записать поверх финального файла напрямую: работа на дефолтах
                 хуже риска половины файла (config.json);
      "ignore" — убрать временный файл и промолчать: запись этого файла не важнее
                 работы вызывающего.
    """
    tmp = path.with_name("%s.%d.tmp" % (path.name, threading.get_ident()))
    error = None
    try:
        tmp.write_text(text, encoding="utf-8")
    except OSError as exc:
        error = exc
    if error is None:
        for attempt in range(max(1, retries)):
            try:
                os.replace(tmp, path)
                return
            except PermissionError as exc:
                error = exc
                time.sleep(0.02 * (attempt + 1))
            except OSError as exc:
                error = exc
                break
    try:
        tmp.unlink()
    except OSError:
        pass
    if on_error == "ignore":
        return
    if on_error == "direct":
        path.write_text(text, encoding="utf-8")
        return
    raise error


def save(cfg: dict) -> None:
    """Записывает конфиг целиком (pretty-print, utf-8).

    Атомарно (write_text_atomic): сначала во временный файл рядом, потом подмена
    одним движением. Оборванная запись (выключили сервер, кончился диск) иначе
    оставляла полфайла, load() видел битый JSON и молча работал на дефолтах —
    без прокси, пароля и формы публикации.

    Подмена отказывает, пока файл в этот миг читает другой поток, — повторы
    внутри помощника; если так и не прошла, конфиг дописывается поверх: работа
    на дефолтах без прокси и пароля хуже риска половины файла."""
    text = json.dumps(cfg, indent=2, ensure_ascii=False) + "\n"
    write_text_atomic(paths.here(CONFIG_FILE), text, on_error="direct")


def update(partial: dict, replace=()) -> dict:
    """Мержит partial поверх текущего конфига, сохраняет, возвращает новый.

    Под _write_lock: read-merge-write атомарен между потоками — HTTP-потоки
    сервера и фоновые воркеры кампании пишут config.json одновременно
    (например /api/login ставит default_account, пока кампания завершает
    проход), без лока записи теряли бы друг друга.

    replace — ключи-словари, которые надо не слить, а заменить целиком
    (proxy_rotate_urls: удалённая строка прокси должна унести свою ссылку,
    а глубокое слияние оставило бы её в конфиге навсегда)."""
    with _write_lock:
        cfg = load()
        for key in replace or ():
            cfg.pop(key, None)
        cfg = _merge(cfg, partial if isinstance(partial, dict) else {})
        save(cfg)
    return cfg


def get(key: str, default=None):
    return load().get(key, default)


# потолок общего числа потоков. Высокий намеренно — предел не должен мешать;
# разумные значения небольшие (много параллельных входов с одного IP TikTok
# встречает риск-режимом, много запросов разом упирают прокси), но это выбор
# пользователя, а не кода.
THREADS_MAX = 1000


def clamp_threads(value) -> int:
    """Число потоков из чего угодно в 1..THREADS_MAX; мусор -> дефолт.

    Отдельной функцией, потому что зажим нужен и при чтении конфига, и при
    проверке того, что прислал UI, и оба места обязаны сходиться."""
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return int(DEFAULTS["threads"])
    return max(1, min(THREADS_MAX, number))


SERVER_WAIT_MAX = 240


def clamp_server_wait(value) -> int:
    """Минуты ожидания перегруженного сервера в 1..SERVER_WAIT_MAX; мусор -> дефолт."""
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return int(DEFAULTS["server_wait_min"])
    return max(1, min(SERVER_WAIT_MAX, number))


def server_wait_min() -> int:
    return clamp_server_wait(load().get("server_wait_min", DEFAULTS["server_wait_min"]))


def threads() -> int:
    """Сколько дел делать одновременно — одно на всю программу (см. DEFAULTS)."""
    return clamp_threads(load().get("threads", DEFAULTS["threads"]))


# границы настройки «как часто обновлять профили», минут: чаще пяти нельзя
# (см. докстроку clamp_refresh_minutes), реже суток смысла нет.
REFRESH_MINUTES_MIN = 5
REFRESH_MINUTES_MAX = 1440


def clamp_refresh_minutes(value) -> int:
    """Минуты между обновлениями профилей из чего угодно в 5..1440; мусор -> 60.

    Умолчание — 60 минут. Нижняя граница — 5 минут: обновление профиля это
    запрос к TikTok через прокси, числа студии стоят двух-трёх запросов на
    аккаунт, а залп по одному соединению ловит капчу — поэтому чаще, чем раз
    в 5 минут, нельзя.

    Отдельной функцией, как clamp_threads: зажим нужен и при чтении конфига,
    и при проверке того, что прислал UI, и оба места обязаны сходиться."""
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return int(DEFAULTS["profile_refresh_minutes"])
    return max(REFRESH_MINUTES_MIN, min(REFRESH_MINUTES_MAX, number))


def path(which: str) -> Path:
    """Абсолютный путь из paths.<which> ('jar'/'ts_guard_config'/'photos_dir')."""
    p = Path(load().get("paths", {}).get(which, DEFAULTS["paths"][which]))
    return p if p.is_absolute() else ROOT / p


def _mask_value(value):
    if isinstance(value, str) and len(value) > 8:
        return value[:4] + "…" + f"({len(value)} симв.)"
    return "****"


def _mask_proxy(value):
    """Прокси: прячет только user:pass, хост:порт оставляет видимым —
    поле должно оставаться редактируемым в UI. Строки без '@' — как есть."""
    if isinstance(value, str) and "@" in value:
        head, _, tail = value.rpartition("@")   # head = scheme://user:pass
        scheme = head.partition("://")[0] + "://"
        return scheme + "***@" + tail
    return value


def _mask_rotate_url(value):
    """Ссылка ротации: хост и путь видны, параметры (там ключ) скрыты."""
    if isinstance(value, str) and "?" in value:
        return value.partition("?")[0] + "?***"
    return value


def masked(cfg: dict = None) -> dict:
    """Копия конфига с замаскированными секретоподобными значениями."""
    def walk(node):
        if isinstance(node, dict):
            out = {}
            for k, v in node.items():
                if k == "proxy":
                    out[k] = _mask_proxy(v)
                elif k == "proxies":
                    out[k] = [_mask_proxy(x) for x in v] if isinstance(v, list) else v
                elif k == "proxy_rotate_urls":
                    out[k] = ({_mask_proxy(a): _mask_rotate_url(b)
                               for a, b in v.items()} if isinstance(v, dict) else v)
                elif _SECRET_KEY_RE.search(str(k)):
                    out[k] = _mask_value(v)
                else:
                    out[k] = walk(v)
            return out
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node
    return walk(cfg if cfg is not None else load())
