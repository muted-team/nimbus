"""Local application event stream."""
import logging
import logging.handlers
import os
import re
import sys
import threading
import time
from collections import deque
from pathlib import Path

from . import config

MAX_ITEMS = 400   # события
MAX_DEBUG = 1200  # подробности: их много, а нужны только свежие
# Прошлый запуск живёт в отдельном кольце, а не в общем с событиями: общее
# кольцо поднятые записи занимали бы целиком, и первые же события текущего
# запуска вытесняли прошлое. Потолок кольца — с запасом даже на самую
# короткую строку файла (отметка времени + [источник] — около 30 байт) при
# потолке файла в 5 МБ (EVENTS_LOG_MAX_BYTES): больше в него физически не
# поместится, то есть на практике поднимается файл целиком, а не кусок.
PAST_ITEMS_MAX = 175_000

_lock = threading.Lock()
_changed = threading.Condition(_lock)  # будит ждущих в wait_since()
# номер запуска: нумерация записей у каждого запуска своя, и клиент, живший
# при прошлом процессе, по нему понимает, что его номера больше не значат
BOOT = "%x" % int(time.time() * 1000)
_items = deque(maxlen=MAX_ITEMS)
# записи прошлого запуска — своё кольцо: свежие события их не вытесняют
_past = deque(maxlen=PAST_ITEMS_MAX)
_debug = deque(maxlen=MAX_DEBUG)
_pulses = {}  # имя состояния -> сколько раз менялось (см. pulse)
_seq = 0
_attached = False
_console = None  # исходный stdout: say() печатает в него мимо переходника

# «[campaign] текст» -> источник campaign
_TAG_RE = re.compile(r"^\[([a-zA-Zа-яА-Я0-9_-]{1,16})\]\s*(.*)$", re.S)

_ERR_RE = re.compile(
    r"(?i)не удал|не вышло|ошибк|провал|не опубликован|исчерпан|протух"
    r"|отказ|капч|fail|error|traceback")
_WARN_RE = re.compile(
    r"(?i)внимание|повтор|retry|ждём|ждем|пуст|остановлен|не сменил|таймаут")
_OK_RE = re.compile(
    r"(?i)\bok\b|успешн|выполнен|опубликован|готово|сохранен")


def _level_of(text: str) -> str:
    """Уровень записи по тексту: ошибка важнее предупреждения, оно — успеха."""
    if _ERR_RE.search(text):
        return "err"
    if _WARN_RE.search(text):
        return "warn"
    if _OK_RE.search(text):
        return "ok"
    return ""


def _record(text, source, level, account, debug):
    """Разобрать строку и положить в свой буфер. None — писать нечего."""
    global _seq
    _lift_past()  # прошлый запуск встаёт раньше первой свежей записи
    # у подробностей отступ слева — часть смысла (строки трассировки)
    text = (text or "").rstrip()
    match = _TAG_RE.match(text.lstrip())
    if match:
        source = source or match.group(1).lower()
        text = match.group(2).strip()
    if not debug:
        # событие — ровно одна строка: перевод строки внутри текста в ленте
        # выглядел бы оборванной второй записью
        text = " ".join(text.split())
    elif not text.strip():
        text = ""
    if not text:
        return None
    if level is None:
        level = _level_of(text)
    with _lock:
        _seq += 1
        item = {"seq": _seq, "ts": time.time(), "source": source or "",
                "account": account or "", "level": level or "",
                "text": text[:1000], "debug": bool(debug)}
        (_debug if debug else _items).append(item)
        _changed.notify_all()
    return item


def add(text: str, source: str = "", level: str = None) -> None:
    """Подробность: строка stdout. source/level можно не указывать —
    источник берётся из префикса «[tag]», уровень определяется по тексту."""
    _record(text, source, level, "", True)


# Файл в logs/: только события say() — «подробности» (add(), см. выше) сюда
# не попадают нарочно, там бывают тела ответов TikTok с живыми токенами, а
# папку logs пользователь целиком отправляет в поддержку. Путь — атрибут
# модуля (не переменная окружения), чтобы проверка подменяла его без правки
# прод-кода; в проде — logs/events.log рядом с app.log (config.ROOT).
EVENTS_LOG_DIR = None
EVENTS_LOG_NAME = "events.log"
# 5 МБ и 3 архива — этого с запасом хватает на «что случилось перед сбоем»,
# а автор инструкции руками файлы из logs/ не чистит: без потолка они бы
# росли бесконечно за месяцы работы кампании.
EVENTS_LOG_MAX_BYTES = 5 * 1024 * 1024
EVENTS_LOG_BACKUPS = 3

_file_lock = threading.Lock()
_file_handler = None       # активный RotatingFileHandler или None (не настроен/недоступен)
_file_handler_path = None  # путь, под который он открыт — смена (проверкой) пересоздаёт


class _QuietRotatingHandler(logging.handlers.RotatingFileHandler):
    """Диск полон, файла нет прав на запись, файл занят другим процессом —
    say() из-за этого падать не должен, а трассировка на каждой строке
    была бы тем самым спамом, которого просили избежать."""

    def handleError(self, record):  # noqa: ARG002 — сигнатура базового класса
        pass


def _events_log_path() -> Path:
    base = EVENTS_LOG_DIR if EVENTS_LOG_DIR is not None else (config.ROOT / "logs")
    return Path(base) / EVENTS_LOG_NAME


# Окно чтения файла событий при первом обращении к журналу — весь файл, а не
# кусок: он и так не может вырасти больше EVENTS_LOG_MAX_BYTES (ротация
# следит), и после перезапуска в ленту должно попасть всё, что было с
# последней чистки или ротации, а не только последняя сотня строк.
_PAST_TAIL_BYTES = EVENTS_LOG_MAX_BYTES
# Строка файла событий, как её пишет _write_event_file:
#   «2026-09-17 01:23:45 err [campaign] alpha: вход не удался»
# — отметка, необязательный уровень, источник в скобках, остаток.
_LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(?: ([a-z]+))? \[([^\]\r\n]*)\] ?(.*)$")

_lifted = False  # хвост файла поднят в ленту — за процесс это делается один раз


def _parse_event_line(line: str):
    """Строка файла событий -> запись журнала; None — строка не нашего вида.

    Разбор мягкий: одна чужая строка не теряет остальные и не роняет старт.
    Остаток строки целиком уходит в `text`, а account остаётся пустым: писатель
    склеивает «аккаунт: текст», и двоеточие в тексте неотличимо от разделителя
    — угадывать аккаунт здесь значит приписать событие не тому."""
    match = _LINE_RE.match(line)
    if not match:
        return None
    try:
        ts = time.mktime(time.strptime(match.group(1), "%Y-%m-%d %H:%M:%S"))
    except (ValueError, OverflowError, OSError):
        return None
    text = match.group(4).strip()
    if not text:
        return None
    return {"ts": ts, "source": match.group(3), "account": "",
            "level": match.group(2) or "", "text": text[:1000],
            "debug": False, "past": True}


def _read_past_items(limit: int = None) -> list:
    """Записи прошлого запуска из файла событий. Без файла, с обрезанным
    хвостом или развернутым в архив — пустой список, без исключения.

    limit=None (по умолчанию) — читать текущее значение PAST_ITEMS_MAX, а не
    то, что было при импорте модуля: подмена атрибута (проверкой) иначе не
    действовала бы, как и подмена EVENTS_LOG_DIR.

    Читается файл целиком (окно чтения — весь его потолок, 5 МБ): неполная
    строка (файл дописан не до конца) отбрасывается, архив (events.log.1) не
    читается вовсе — в нём то же самое, что уже было."""
    if limit is None:
        limit = PAST_ITEMS_MAX
    try:
        with _events_log_path().open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            start = max(0, fh.tell() - _PAST_TAIL_BYTES)
            # на байт левее окна: по нему видно, попали ли мы на границу строки
            # (см. ниже). Сам байт в разбор не идёт — он только для этого.
            fh.seek(max(0, start - 1))
            raw = fh.read()
    except OSError:
        return []
    if start:
        # Начали с середины строки: первый кусок — обрывок, а не запись. Если
        # байт перед окном — перевод строки, окно начинается ровно с целой
        # строки, и срезать её целиком нельзя: partition() отделяет только
        # обрывок, для этого и прочитан байт левее.
        raw = raw.partition(b"\n")[2]
    if raw and not raw.endswith(b"\n"):
        cut = raw.rfind(b"\n")  # последняя строка не дописана — выкидываем
        raw = raw[:cut + 1] if cut >= 0 else b""
    items = []
    for line in raw.decode("utf-8", "replace").splitlines()[-limit:]:
        item = _parse_event_line(line)
        if item is not None:
            items.append(item)
    return items


def _lift_past() -> None:
    """Один раз за процесс подложить в ленту хвост файла событий.

    Номера записей прошлого запуска идут первыми, а _seq продолжается с них:
    после перезапуска since(0) отдаёт их раньше свежих и в том же порядке, а
    нумерация не разрывается. Живут они в своём кольце (_past), а не в общем с
    событиями: общее кольцо поднятые записи занимали целиком, и первые же
    события текущего запуска вытесняли прошлое. Зовётся лениво — из первой
    записи журнала и из первого чтения, — поэтому подмена EVENTS_LOG_DIR
    проверкой работает: хвост читается уже после неё (для повторного разбора
    проверка сбрасывает `_lifted`).

    Файл читается до замка: разбор хвоста (до 512 КиБ) — работа с диском, и
    держать на ней замок значит останавливать say() и since() у всех потоков.
    Гонка безвредна: второй поток разберёт тот же хвост и, найдя `_lifted`,
    выбросит свою копию."""
    global _lifted, _seq
    if _lifted:
        return
    items = _read_past_items()
    with _lock:
        if _lifted:
            return
        _lifted = True
        for item in items:
            _seq += 1
            item["seq"] = _seq
            _past.append(item)
        if _past:
            _changed.notify_all()


def _file_writer():
    """Отдаёт настроенный логгер для файла событий или None, если путь
    недоступен. Хендлер держит файл открытым между вызовами (RotatingFile-
    Handler сам закрывает поток перед переименованием при ротации — на
    Windows иначе упало бы), пересоздаётся только если путь поменялся
    (тестовая подмена EVENTS_LOG_DIR) — на каждой строке ничего не трогаем."""
    global _file_handler, _file_handler_path
    path = _events_log_path()
    with _file_lock:
        if _file_handler_path == path:
            return _file_handler
        if _file_handler is not None:
            try:
                _file_handler.close()
            except Exception:  # noqa: BLE001
                pass
            _file_handler = None
        _file_handler_path = path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handler = _QuietRotatingHandler(
                str(path), maxBytes=EVENTS_LOG_MAX_BYTES,
                backupCount=EVENTS_LOG_BACKUPS, encoding="utf-8", delay=True)
            handler.setFormatter(logging.Formatter("%(message)s"))
            _file_handler = handler
        except Exception:  # noqa: BLE001 — папка недоступна (нет прав, файл вместо папки)
            _file_handler = None
        return _file_handler


_file_logger = logging.getLogger("tiktok_web_api.events")
_file_logger.setLevel(logging.INFO)
_file_logger.propagate = False  # не дублировать в чей-то настроенный root-логгер


def _write_event_file(item: dict, account: str) -> None:
    handler = _file_writer()
    if handler is None:
        return
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(item["ts"]))
    prefix = "%s%s [%s]" % (stamp, (" " + item["level"]) if item["level"] else "",
                             item["source"] or "log")
    line = "%s %s%s" % (prefix, account + ": " if account else "", item["text"])
    # handler.handle(), не handler.emit(): только так строки из разных
    # потоков публикации пишутся под внутренним замком хендлера и не
    # перемешиваются построчно.
    record = _file_logger.makeRecord(
        _file_logger.name, logging.INFO, "", 0, line, (), None)
    try:
        handler.handle(record)
    except Exception:  # noqa: BLE001 — запись в файл не должна ронять say()
        pass


def say(text: str, level: str = None, account: str = "", source: str = "") -> None:
    """Событие для ленты: короткая понятная строка, без кодов и заголовков.

    level — "ok" | "warn" | "err" | "" (нейтрально); None — по тексту.
    account — аккаунт, к которому относится событие: UI выводит его отдельной
    колонкой, в текст имя вписывать не нужно. Префикс «[tag]» в тексте
    допустим — так в say() можно направить готовый колбэк log= модуля."""
    item = _record(text, source, level, account, False)
    if item is None:
        return
    _write_event_file(item, account)
    line = "[%s] %s%s\n" % (item["source"] or "log",
                            account + ": " if account else "", item["text"])
    stream = _console if _attached else sys.stdout
    if stream is None:
        return  # exe без консоли
    try:
        stream.write(line)
        stream.flush()
    except Exception:  # noqa: BLE001 — консоль не главное, запись уже в журнале
        pass


def teller(account: str = "", source: str = ""):
    """say(), привязанный к аккаунту — для колбэков log= (смена IP прокси)."""
    return lambda text, level=None: say(text, level, account, source)


def since(after: int = 0, limit: int = 300, debug: bool = False) -> dict:
    """Записи с номером больше after (0 — весь буфер, но не длиннее limit).
    debug — вместе с подробностями, иначе только события.

    Возвращает {"items": [...], "seq": номер последней записи}: UI хранит seq
    и следующим запросом получает только новое. В первой выдаче за процесс есть
    и записи прошлого запуска (поле past) — они идут раньше свежих."""
    _lift_past()
    with _lock:
        # прошлое и события — два кольца; их номера не перемешаны (прошлому
        # достаются первые), поэтому хватает сложения, а не сортировки
        items = [x for x in _past if x["seq"] > after]
        items += [x for x in _items if x["seq"] > after]
        if debug:
            items += [x for x in _debug if x["seq"] > after]
            items.sort(key=lambda x: x["seq"])
        last = _seq
    if limit and len(items) > limit:
        items = items[-limit:]
    return {"items": items, "seq": last}


def pulses() -> dict:
    """Текущие счётчики pulse() — отправная точка для wait_since(pulses=...)."""
    _lift_past()
    with _lock:
        return dict(_pulses)


def pulse(name: str) -> None:
    """Отметить, что состояние name (например, «campaign») поменялось: ждущие
    в wait_since() проснутся, и живой поток UI пришлёт свежий снимок."""
    with _lock:
        _pulses[name] = _pulses.get(name, 0) + 1
        _changed.notify_all()


def wait_since(after: int, debug: bool = False, timeout: float = 15.0,
               limit: int = 0, pulses: dict = None) -> dict:
    """Как since(), но если нового ещё нет — ждёт его до timeout секунд.
    pulses — счётчики pulse(), уже известные ждущему: их изменение тоже
    будит. Ответ дополнен текущими счётчиками ("pulses"). Пустой items и
    те же pulses — за timeout ничего не случилось."""
    _lift_past()

    def fresh():
        if pulses is not None and _pulses != pulses:
            return True
        # прошлый запуск тоже новое для того, кто пришёл с after=0: подняли его
        # только что, и ждать из-за него timeout незачем
        if _past and _past[-1]["seq"] > after:
            return True
        if _items and _items[-1]["seq"] > after:
            return True
        return bool(debug and _debug and _debug[-1]["seq"] > after)

    with _changed:
        _changed.wait_for(fresh, timeout)
        now = dict(_pulses)
    chunk = since(after, limit, debug)
    chunk["pulses"] = now
    return chunk


def last_seq() -> int:
    _lift_past()
    with _lock:
        return _seq


def _clear_file() -> None:
    """Стереть файл событий и его архивы ротации.

    Без этого «Очистить» не значило бы очистить: лента пропала бы с экрана
    только до перезапуска, а после него _lift_past() снова поднял бы старый
    файл в ленту. Хендлер закрывается и сбрасывается заранее — на Windows
    нельзя удалить файл, пока он открыт другим хендлом того же процесса."""
    global _file_handler, _file_handler_path
    with _file_lock:
        if _file_handler is not None:
            try:
                _file_handler.close()
            except Exception:  # noqa: BLE001
                pass
            _file_handler = None
        _file_handler_path = None
        path = _events_log_path()
        candidates = [path] + [Path("%s.%d" % (path, i))
                               for i in range(1, EVENTS_LOG_BACKUPS + 1)]
        for candidate in candidates:
            try:
                candidate.unlink()
            except OSError:
                pass  # нет файла — не ошибка


def clear() -> None:
    """Очистить журнал целиком: память (записи прошлого запуска и текущего) и
    файл на диске вместе с архивами ротации — очистка, после которой прошлое
    вернулось бы на экран после перезапуска, обнулением не выглядит."""
    with _lock:
        _items.clear()
        _past.clear()
        _debug.clear()
    _clear_file()


class _Tap:
    """Переходник поверх stdout/stderr: печатает как обычно и копит строки.

    Собирает по переводам строк — print() приходит двумя вызовами write()
    («текст» и «\\n»), а незавершённый хвост (progress вида «...») не должен
    сыпаться в журнал отдельными кусками."""

    def __init__(self, stream, source=""):
        self._stream = stream
        self._source = source
        self._buf = ""
        self._buf_lock = threading.Lock()

    def write(self, text):
        if self._stream is not None:
            try:
                self._stream.write(text)
            except Exception:  # noqa: BLE001 — консоли может не быть (exe без окна)
                pass
        with self._buf_lock:
            self._buf += text or ""
            lines = self._buf.split("\n")
            self._buf = lines.pop()
        for line in lines:
            add(line, source=self._source)
        return len(text or "")

    def flush(self):
        if self._stream is not None:
            try:
                self._stream.flush()
            except Exception:  # noqa: BLE001
                pass

    def isatty(self):
        return bool(getattr(self._stream, "isatty", lambda: False)())

    @property
    def encoding(self):
        return getattr(self._stream, "encoding", "utf-8")


def attach_stdout() -> None:
    """Подменить sys.stdout/sys.stderr переходниками (повторный вызов — no-op)."""
    global _attached, _console
    if _attached:
        return
    _attached = True
    _console = sys.stdout
    sys.stdout = _Tap(sys.stdout)
    sys.stderr = _Tap(sys.stderr, source="stderr")
