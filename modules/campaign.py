"""Client campaign orchestration."""
import json
import random
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from . import accounts as accounts_mod
from . import (batch_publish, config, eventlog, humanize, proxy_pool, purge, signin)
from . import proxies as proxies_mod

# сколько раз воркер пересаживается на другой прокси, если шаг сорвался на сети
PROXY_SWITCHES = 2
# сколько раз после серии сбоев прокси признаётся мёртвым и шаг идёт заново
# через другой — дальше сбой считается сбоем аккаунта
PROXY_ROUNDS = 2


class CampaignAlreadyRunningError(RuntimeError):
    """Кампания уже выполняется — start_campaign не может запустить вторую параллельно."""


def _now() -> str:
    return datetime.now().isoformat()


def _initial_state() -> dict:
    return {
        "status": "idle",
        "accounts_total": 0,
        "accounts_done": 0,
        "queued": [],       # username всего прохода в порядке очереди
        "posts_per_account": 0,
        "threads": 1,
        "workers": [],      # [{account, step, posts_done}] — живые воркеры
        "results": [],      # [{account, ok, posts_done, posts_lost, reason}]
        "stop_reason": None,
        "started_at": None,
        "finished_at": None,
        "updated_at": _now(),
        "stop_requested": False,
        "abort_reason": None,  # проход остановлен программой, а не пользователем
        "restored": False,  # отчёт поднят с диска после перезапуска, а не свежий проход
        # повторные проходы кругами: repeat — крутить бесконечно, round — номер
        # текущего круга (с 1), next_run_at — когда стартует следующий (статус
        # "waiting" между кругами), rounds_done — сколько кругов уже завершено
        "repeat": False,
        "media": "photo",   # что публикует проход: photo | video
        "round": 0,
        "rounds_done": 0,
        "next_run_at": None,
        "paused_accounts": [],  # unknown/challenge: не повторять в следующих кругах
    }


_state_lock = threading.Lock()
_run_lock = threading.Lock()
_state = _initial_state()
_thread = None
# читаем файл отчёта один раз за процесс (см. _lift_saved_report)
_report_lifted = False

# повторные проходы кругами: пауза между кругами зажимается в эти пределы.
# Минимум небольшой (быстро проверить круг на живой машине), потолок большой —
# «раз в сутки» это выбор пользователя, а не предел кода.
REPEAT_MIN_SEC = 10
REPEAT_MAX_SEC = 30 * 24 * 3600  # 30 суток
# отчёт законченного прохода остаётся и на диске: программу закрыли (обновление,
# ребут, падение) — «не пролито» можно повторить кнопкой, а «снято за нарушение
# правил» человек увидит до того, как TikTok заблокирует аккаунт. Путь —
# атрибут модуля, чтобы проверка подменяла каталог без правки прод-кода (как
# EVENTS_LOG_DIR в eventlog). Лежит в logs/: папка не коммитится, и имена
# аккаунтов из отчёта не уезжают в репозиторий.
REPORT_DIR = None  # None -> logs/ рядом с app.log
REPORT_NAME = "campaign_report.json"


def _report_path() -> Path:
    base = REPORT_DIR if REPORT_DIR is not None else (config.ROOT / "logs")
    return Path(base) / REPORT_NAME


def _clamp_repeat(min_sec, max_sec):
    """Пара границ паузы между кругами в секундах: целые, min<=max, в пределах
    [REPEAT_MIN_SEC, REPEAT_MAX_SEC]. Мусор -> обе равны REPEAT_MIN_SEC."""
    def _sec(v):
        try:
            return max(REPEAT_MIN_SEC, min(REPEAT_MAX_SEC, int(v)))
        except (TypeError, ValueError):
            return REPEAT_MIN_SEC
    lo, hi = _sec(min_sec), _sec(max_sec)
    return (lo, hi) if lo <= hi else (hi, lo)


def start_campaign(slots, caption, title, min_delay_ms, max_delay_ms,
                   posts_per_account, limit=None, threads=None,
                   delete_before=False, creatives="copies",
                   keep_photos=False, accounts=None,
                   repeat=False, repeat_min_sec=0, repeat_max_sec=0,
                   media="photo") -> dict:
    """Запускает фоновый оркестратор очереди аккаунтов и сразу возвращает
    снапшот статуса (не ждёт первого аккаунта).

    slots/caption/title/min_delay_ms/max_delay_ms — общие на всю кампанию,
    передаются как есть в каждый воркер (валидация — забота вызывающего,
    main.py, здесь не перепроверяется).
    posts_per_account — сколько постов публикует каждый аккаунт за свой
    заход в очереди, целое >= 1.
    limit — максимум постов на аккаунт за проход числом; None -> берётся
    равным posts_per_account (это теперь одно и то же). Параметр оставлен
    для совместимости вызова.
    threads — сколько аккаунтов обрабатываются одновременно (1..N, 1 =
    старое последовательное поведение). None -> общая настройка config.threads().
    delete_before — что снести с аккаунта перед заливом, числовым кодом:
      0 — ничего не трогать;
      -1 — все посты аккаунта;
      -2 — столько же, сколько публикуем (posts_per_account);
      N больше нуля — ровно N последних постов.
    creatives — batch_publish.CREATIVES; keep_photos — не удалять фото из папок.
    accounts — список username: проход только по ним (в порядке списка).
      None/пустой список — по всем аккаунтам accounts.json, как раньше.
      Отбор по известным именам: незнакомое отбрасывается (UI шлёт имена из
      того же списка), несовпадение регистра — не повод рушить запуск.
    repeat — крутить проходы кругами: закончив круг по всем аккаунтам,
      кампания уходит в статус "waiting" на случайную паузу из
      [repeat_min_sec, repeat_max_sec] секунд и начинает следующий круг —
      так до «Остановить». Если включено «снести прошлые посты», каждый круг
      сносит и заливает заново; если нет — просто добавляет новые посты.
      repeat=False (по умолчанию) — один проход, как раньше.
    media — "photo" (карусель из папок-слотов) или "video" (один ролик на
      пост, slots — единственная папка с видео).

    Один проход по всем аккаунтам, которые сейчас в accounts.json — сколько
    их в файле, столько заходов, каждый ровно один раз, дальше кампания сама
    завершается статусом "stopped" (или уходит в новый круг при repeat).

    Если кампания уже выполняется (_run_lock занят) — бросает
    CampaignAlreadyRunningError, ничего не меняя в состоянии.
    """
    global _thread

    if not _run_lock.acquire(blocking=False):
        raise CampaignAlreadyRunningError("кампания уже выполняется")

    if limit is None:
        limit = posts_per_account
    # None -> общая настройка «потоки»; иначе явное число из запроса, зажатое
    # тем же правилом, что и настройка (config.clamp_threads)
    threads = config.threads() if threads is None else config.clamp_threads(threads)
    delete_before = normalize_delete_before(delete_before)
    repeat = bool(repeat)
    repeat_min_sec, repeat_max_sec = _clamp_repeat(repeat_min_sec, repeat_max_sec)
    media = media if media in ("photo", "video") else "photo"

    with _state_lock:
        _state.clear()
        _state.update(_initial_state())
        _state.update({
            "status": "running",
            "threads": threads,
            "posts_per_account": posts_per_account,
            "repeat": repeat,
            "media": media,
            "started_at": _now(),
            "updated_at": _now(),
        })
    _pulse()

    _thread = threading.Thread(
        target=_run_campaign,
        args=(slots, caption, title, min_delay_ms, max_delay_ms,
              posts_per_account, limit, threads, delete_before,
              creatives, bool(keep_photos), accounts,
              repeat, repeat_min_sec, repeat_max_sec, media),
        daemon=True,
    )
    _thread.start()

    return get_status()


def wait_idle() -> None:
    """Дождаться, пока прошлый проход отпустит _run_lock: статус «готово» он
    ставит раньше, чем отпускает замок, и start_campaign сразу за ним ловит
    CampaignAlreadyRunningError."""
    while not _run_lock.acquire(blocking=False):
        time.sleep(0.01)
    _run_lock.release()


def get_status() -> dict:
    """Копия _state под _state_lock — безопасно вызывать из HTTP-потоков,
    пока фоновые воркеры пишут параллельно. Списки и строки воркеров
    копируются: JSON собирается уже без замка.

    Плюс счёт постов прохода: posts_total — план (аккаунтов × постов на
    аккаунт), posts_done — опубликовано, включая идущих прямо сейчас,
    posts_failed — не вышло: у закончивших аккаунтов разница между планом и
    сделанным (вход не удался, пост отклонён), posts_removed — сколько постов
    снято с аккаунтов за нарушение правил (это не посты прохода: сводка по
    уведомлениям аккаунта, см. _read_notices). Остановка пользователем в
    posts_failed не идёт — эти посты просто не делались.

    Если проходов в этом процессе ещё не было, а на диске лежит отчёт
    последнего — первый вызов поднимает его (_lift_saved_report): status
    остаётся idle, а restored=True говорит, что это отчёт прошлого запуска."""
    _lift_saved_report()
    with _state_lock:
        st = dict(_state)
        st["workers"] = [dict(w) for w in _state["workers"]]
        st["results"] = [dict(r) for r in _state["results"]]
        st["queued"] = list(_state["queued"])
    st["posts_total"] = st["accounts_total"] * (st.get("posts_per_account") or 0)
    st["posts_done"] = (sum(r["posts_done"] for r in st["results"])
                        + sum(w.get("posts_done") or 0 for w in st["workers"]))
    st["posts_failed"] = sum(r.get("posts_lost") or 0 for r in st["results"])
    st["report"] = _report(st["results"])
    st["posts_removed"] = st["report"]["posts_removed"]
    return st


def _report(results: list) -> dict:
    """Отчёт по закончившим аккаунтам, четыре категории по username:
      published — пролитые (хоть один пост вышел),
      failed    — не пролитые (ни одного поста, но аккаунт жив),
      banned    — забаненные/удалённые (отключены из списка),
      removed   — с аккаунта сняли посты за нарушение правил (хоть один).
    Плюс posts — сколько всего постов вышло, и posts_removed — сколько постов
    снято за нарушение правил. Аккаунт, который ещё в работе, в отчёт не
    попадает (его нет в results) — счёт идёт по завершённым."""
    published, failed, banned, removed = [], [], [], []
    for r in results:
        if r.get("banned"):
            banned.append(r["account"])
        elif r.get("posts_done"):
            published.append(r["account"])
        else:
            failed.append(r["account"])
        if r.get("removed"):
            removed.append(r["account"])
    return {"published": published, "failed": failed, "banned": banned,
            "removed": removed,
            "posts": sum(r["posts_done"] for r in results),
            "posts_removed": sum(r.get("removed") or 0 for r in results)}


def _save_report() -> None:
    """Кладёт итог законченного прохода на диск — он должен пережить
    перезапуск программы (см. _lift_saved_report). Пишем только отчёт с
    аккаунтами: пустой проход (нет аккаунтов, нет живых прокси) ничего не
    рассказывает, и затирать им настоящий отчёт прошлого раза незачем.

    Поле report не пишется: при подъёме его соберёт _report() из results —
    ровно так же, как для свежего прохода.

    Запись — общим приёмом программы (config.write_text_atomic): временный
    файл рядом и подмена одним движением. Отчёт может быть занят другой
    программой (антивирус, просмотрщик, второй запуск), и тогда подмена на
    Windows отказывает: помощник повторяет её десяток коротких раз, а не
    теряет отчёт сразу, как делал свой os.replace. Не прошла и подмена —
    отчёт теряется, но проход из-за него не роняется: причина уходит строкой
    в консоль, а повторить проход можно из UI."""
    with _state_lock:
        results = [dict(r) for r in _state["results"]]
        if not results:
            return
        snapshot = {
            "results": results,
            "accounts_total": _state["accounts_total"],
            "accounts_done": _state["accounts_done"],
            "posts_per_account": _state["posts_per_account"],
            "threads": _state["threads"],
            "media": _state["media"],
            "started_at": _state["started_at"],
            "finished_at": _state["finished_at"],
            "stop_reason": _state["stop_reason"],
        }
    path = _report_path()
    text = json.dumps({"saved_at": _now(), "pass": snapshot},
                      ensure_ascii=False, indent=2)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # on_error="raise": помощник повторяет подмену, пока файл занят другой
        # программой, а решение о сбое оставляет вызывающему — здесь это
        # строка в консоль, проход из-за отчёта не роняется (см. выше)
        config.write_text_atomic(path, text, on_error="raise")
    except OSError as exc:
        print("[campaign] отчёт прохода не сохранён: %s" % exc)


def _report_int(value) -> int:
    """Число из поля отчёта на диске — счётчика аккаунта или поля прохода: нет
    ключа, null, строка, отрицательное — всё это ноль. Файл писал не только наш
    код и править его мог человек, а ронять из-за поля нечего.

    OverflowError — тоже сюда: `json.loads` принимает литералы Infinity и NaN,
    а `int(float("inf"))` падает. Без него первый же get_status после старта с
    таким файлом отдавал 500."""
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return 0


def _report_flag(value) -> bool:
    """Признак из поля отчёта на диске (сейчас это поле banned у аккаунта).

    Отдельно от _report_int: значение читается по истинности, а строка "false"
    в python истинна — живой аккаунт с `"banned": "false"` в файле уезжал в
    категорию «забанено». Строки разбираются явно: «нет» — "false", "0", "no",
    "none" и пустая; остальное — «да»."""
    if isinstance(value, str):
        return value.strip().lower() not in ("", "false", "0", "no", "none")
    return bool(value)


def _load_report() -> dict:
    """Отчёт последнего прохода с диска; нет файла, битый или чужой — пустой
    словарь. Ронять из-за него get_status нечем: отчёта просто не будет, а
    счётчики и признак забаненности каждого аккаунта приводятся к своим типам
    здесь, на входе (_report_int, _report_flag) — иначе пропавший posts_done
    валил бы 500 каждый следующий get_status, пока программу не перезапустят.
    """
    try:
        data = json.loads(_report_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    snapshot = data.get("pass") if isinstance(data, dict) else None
    if (not isinstance(snapshot, dict)
            or not isinstance(snapshot.get("results"), list)):
        return {}
    results = []
    for r in snapshot["results"]:
        if not isinstance(r, dict) or not r.get("account"):
            continue
        r = dict(r)
        for field in ("posts_done", "posts_lost", "removed"):
            r[field] = _report_int(r.get(field))
        r["banned"] = _report_flag(r.get("banned"))
        results.append(r)
    if not results:
        return {}
    snapshot["results"] = results
    return snapshot


def _lift_saved_report() -> None:
    """Поднимает в _state отчёт последнего законченного прохода — один раз за
    процесс, лениво из первого get_status(). Строкой в app.py это было бы
    в чужой зоне (app-window). Статус остаётся idle: прохода сейчас не идёт,
    а признак прошлого запуска — поле restored.

    Подъём одноразовый, и первый же проход его снимает: начавшись, проход
    стирает карточку «Результаты» вместе с пометкой restored — пустой проход
    (нет аккаунтов, нет живых прокси) тоже. Решено так: карточка показывает
    итог проходов этого запуска программы, а не прошлого. Отчёт прошлого раза
    при этом не пропадает: пустой проход не затирает файл (см. _save_report),
    и после перезапуска программы карточка поднимется снова.

    Числа прохода (аккаунтов, постов на аккаунт, потоков) приводятся к целым
    здесь же: строка вместо числа в файле — тоже не повод отдавать 500, а
    posts_total считается умножением.

    Флаг «поднято» ставится после разбора файла, а не до: сбой разбора не
    должен закрывать подъём до конца жизни процесса — иначе отчёт не вернулся
    бы, даже если файл потом починили."""
    global _report_lifted
    with _state_lock:
        if _report_lifted:
            return
    saved = _load_report()
    media = saved.get("media")
    with _state_lock:
        _report_lifted = True
        if not saved:
            return
        # пока читали диск, проход мог начаться или закончиться — тогда
        # сохранённое уже не «последнее», и подмешивать его к живому нельзя
        if _state["status"] != "idle" or _state["results"]:
            return
        results = saved["results"]
        _state.update({
            "results": [dict(r) for r in results],
            "accounts_total": _report_int(saved.get("accounts_total")),
            "accounts_done": (_report_int(saved.get("accounts_done"))
                              or len(results)),
            "posts_per_account": _report_int(saved.get("posts_per_account")),
            "threads": _report_int(saved.get("threads")) or 1,
            "media": media if media in ("photo", "video") else "photo",
            "started_at": saved.get("started_at"),
            "finished_at": saved.get("finished_at"),
            "stop_reason": saved.get("stop_reason"),
            "restored": True,
            "updated_at": _now(),
        })


def _pulse() -> None:
    """Состояние поменялось — живой поток UI (GET /api/stream) пришлёт
    свежий снимок. Звать вне _state_lock."""
    eventlog.pulse("campaign")


def request_stop() -> dict:
    """Идемпотентна: если статус не running/stopping — просто возвращает
    текущий get_status(), это не ошибка. Иначе ставит флаг остановки и
    статус "stopping": живые воркеры просят остановиться (аккуратно, до
    конца текущего поста), новые аккаунты из очереди не берутся, а круговая
    кампания в паузе между кругами (waiting) прерывает ожидание и завершается —
    следующий круг не начнётся."""
    with _state_lock:
        live = _state["status"] in ("running", "stopping", "waiting")
        if live:
            _state["status"] = "stopping"
            _state["stop_requested"] = True
            _state["next_run_at"] = None
            _state["updated_at"] = _now()
    if live:
        _pulse()
    return get_status()


def _finish(reason: str, is_error: bool = False) -> None:
    with _state_lock:
        _state["status"] = "error" if is_error else "stopped"
        _state["stop_reason"] = reason
        _state["finished_at"] = _now()
        _state["next_run_at"] = None
        _state["updated_at"] = _now()
        results = list(_state["results"])
    _pulse()
    _save_report()  # итог переживёт перезапуск программы (см. _lift_saved_report)
    rep = _report(results)
    posts = rep["posts"]
    # отчёт по аккаунтам: пролитые / не пролитые / забаненные / со снятыми постами
    parts = ["постов %d" % posts,
             "пролито %d" % len(rep["published"]),
             "не пролито %d" % len(rep["failed"])]
    if rep["banned"]:
        parts.append("забанено %d" % len(rep["banned"]))
    if rep["posts_removed"]:
        parts.append("снято за нарушение правил %d" % rep["posts_removed"])
    summary = ", ".join(parts)
    failed = len(rep["failed"]) + len(rep["banned"])
    if is_error:
        eventlog.say("публикация прервана: %s" % reason, "err", source="campaign")
    elif results:
        eventlog.say("%s: %s" % (reason, summary),
                     "warn" if failed or not posts or rep["removed"] else "ok",
                     source="campaign")
        if rep["banned"]:
            eventlog.say("забанены и отключены: %s" % ", ".join(rep["banned"]),
                         "err", source="campaign")
        if rep["removed"]:
            # сводка по уведомлениям: у этих аккаунтов посты уже снимали за
            # нарушение правил — следующий шаг TikTok обычно блокировка
            eventlog.say("сняты посты за нарушение правил: %s"
                         % ", ".join(rep["removed"]), "err", source="campaign")
    else:
        eventlog.say(reason, "warn", source="campaign")


def _record_result(username: str, ok: bool, posts_done: int, reason: str,
                   banned: bool = False, removed: int = 0) -> None:
    """Итог аккаунта. Строка воркера уходит тем же движением: иначе между
    итогом и _worker_clear его посты посчитались бы в posts_done дважды.
    banned=True — аккаунт забанен/удалён у TikTok (в отчёте отдельной
    категорией; из accounts.json его уже убрал _ban_account).
    removed — сколько постов аккаунта снято за нарушение правил (уведомления
    читаются до публикации, см. _read_notices)."""
    with _state_lock:
        # недоделанное из-за остановки пользователем — не провал
        lost = 0 if _state["stop_requested"] else max(
            0, (_state.get("posts_per_account") or 0) - posts_done)
        _state["results"].append({
            "account": username, "ok": ok, "banned": banned,
            "posts_done": posts_done, "posts_lost": lost, "reason": reason,
            "removed": removed or 0,
        })
        _state["workers"] = [w for w in _state["workers"]
                             if w["account"] != username]
        _state["updated_at"] = _now()
    _pulse()


def _advance(processed: int) -> None:
    with _state_lock:
        _state["accounts_done"] = processed
        _state["updated_at"] = _now()
    _pulse()


def _worker_clear(account: str) -> None:
    """Воркер закончился (успех/провал) — уходит из списка живых."""
    with _state_lock:
        before = len(_state["workers"])
        _state["workers"] = [w for w in _state["workers"]
                             if w["account"] != account]
        changed = len(_state["workers"]) != before
        _state["updated_at"] = _now()
    if changed:
        _pulse()


def _worker_set(account: str, step: str, posts_done: int = 0) -> None:
    """Живой воркер сменил шаг/счётчик постов — обновляем его строку.
    Воркер публикации зовёт это раз в полсекунды и с теми же значениями —
    живой поток UI будим только на настоящее изменение."""
    with _state_lock:
        for w in _state["workers"]:
            if w["account"] == account:
                changed = w["step"] != step or w["posts_done"] != posts_done
                w["step"] = step
                w["posts_done"] = posts_done
                w["updated"] = _now()
                break
        else:
            changed = True
            _state["workers"].append({"account": account, "step": step,
                                      "posts_done": posts_done, "updated": _now()})
        _state["updated_at"] = _now()
    if changed:
        _pulse()


def _stop_requested() -> bool:
    with _state_lock:
        return _state["stop_requested"]


def _abort(reason: str) -> None:
    """Остановить проход по причине программы (живых прокси так и не
    появилось): как «Остановить», только итогом будет reason, а не
    «остановлено пользователем». Первая причина остаётся."""
    with _state_lock:
        if not _state["abort_reason"]:
            _state["abort_reason"] = reason
        _state["stop_requested"] = True
        if _state["status"] == "running":
            _state["status"] = "stopping"
        _state["updated_at"] = _now()
    _pulse()


# Коды настройки «снести посты перед заливом» — так она ходит по API и лежит
# в конфиге. Число больше нуля — ровно столько постов.
DELETE_OFF = 0     # не трогать ленту
DELETE_ALL = -1    # снести все посты аккаунта
DELETE_SAME = -2   # снести столько же, сколько сейчас публикуем


def normalize_delete_before(value):
    """Приводит настройку «снести посты перед заливом» к числовому коду.

    0 — не сносить, -1 — сносить всё, -2 — сколько публикуем, N>0 — ровно N.
    Понимает и прежние форматы из старых конфигов: булев флаг и слова
    "all"/"все"/"same"."""
    if value is None or value is False:
        return DELETE_OFF
    if value is True:
        return DELETE_SAME
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("", "off", "no", "none", "false"):
            return DELETE_OFF
        if v in ("all", "все", "всё"):
            return DELETE_ALL
        if v in ("same", "true", "yes"):
            return DELETE_SAME
        value = v
    try:
        n = int(value)
    except (TypeError, ValueError):
        return DELETE_OFF
    if n in (DELETE_ALL, DELETE_SAME):
        return n
    return n if n > 0 else DELETE_OFF


_NO_PROXY_ABORT = "ни один прокси не отвечал %d мин — публикация остановлена" % (
    proxy_pool.WAIT_SEC // 60)
_ALL_THREADS_STOPPED = "прокси всех потоков перестали отвечать — публикация остановлена"


def _wait_alive(username: str) -> None:
    """Живых прокси нет — ждать до proxy_pool.WAIT_SEC, пока оживёт хоть один.
    Не дождались — проход останавливается целиком (_abort) и летит
    NoAliveProxy: пропускать аккаунт за аккаунтом из-за прокси нельзя, виноват
    не аккаунт."""
    if _stop_requested():
        raise proxy_pool.NoAliveProxy(proxy_pool.NO_ALIVE)
    _worker_set(username, "wait_proxy")
    if not proxy_pool.wait_usable(stop=_stop_requested, task="publish"):
        if not _stop_requested():
            _abort(_NO_PROXY_ABORT)
        raise proxy_pool.NoAliveProxy(proxy_pool.NO_ALIVE)


def _take_proxy(username: str) -> "proxy_pool.Lease":
    """Аренда прокси на аккаунт: наименее занятый живой. Живых нет — ждём
    (_wait_alive). Пустой url — прокси выключены."""
    while True:
        try:
            return proxy_pool.lease(recheck=False, task="publish")
        except proxy_pool.ProxySelectionError:
            raise
        except proxy_pool.NoAliveProxy:
            _wait_alive(username)


def _switch_proxy(held, username: str) -> None:
    """Шаг сорвался на сети: куда дальше — решает proxy_pool.reseat
    (пересадка или остановка потока, по настройке). Живых не дождались —
    проход останавливается целиком, как в _wait_alive."""
    failed = held.url
    if not proxy_pool.reseat(held, stop=_stop_requested,
                             waiting=lambda on: on and _worker_set(username, "wait_proxy")):
        if not _stop_requested():
            _abort(_NO_PROXY_ABORT)
        raise proxy_pool.NoAliveProxy(proxy_pool.NO_ALIVE)
    _worker_set(username, "login")
    if held.url != failed:
        print("[campaign] %s: сбой сети через %s — пересаживаюсь на %s"
              % (username, proxy_pool.short(failed), proxy_pool.short(held.url)))
    else:
        print("[campaign] %s: сбой сети через %s — повтор по новому соединению"
              % (username, proxy_pool.short(failed)))


def _net_retry(step, held, username: str):
    """Шаг воркера с пересадками при сбое сети.

    step(proxy) -> (результат, сорвалось_на_сети). Возвращает (результат,
    сорвалось_на_сети); прокси, на котором закончили, — held.url.

    Сбой сети — PROXY_SWITCHES пересадок подряд. Не помогло — прокси
    проверяется тут же, не дожидаясь фона: мёртв — виноват не аккаунт, шаг
    идёт заново через живой (или воркер ждёт, пока оживёт хоть один). Жив —
    сбой остаётся за аккаунтом. Без этой проверки аккаунты, которые были в
    работе в момент смерти прокси, успевали провалиться раньше, чем прокси
    признавали мёртвым."""
    rounds = 0
    while True:
        for switch in range(PROXY_SWITCHES + 1):
            result, network = step(held.url)
            if not network:
                return result, False
            if held.url and switch < PROXY_SWITCHES:
                _switch_proxy(held, username)
        rounds += 1
        if (not held.url or rounds > PROXY_ROUNDS
                or proxy_pool.check(held.url)["state"] != "dead"):
            return result, True
        _switch_proxy(held, username)


def resolve_delete_count(spec, posts_per_account):
    """Во что превращается код настройки для конкретного аккаунта:
    None (не удалять), "all" (вся лента) или положительное число постов."""
    code = normalize_delete_before(spec)
    if code == DELETE_OFF:
        return None
    if code == DELETE_ALL:
        return "all"
    if code == DELETE_SAME:
        return posts_per_account if posts_per_account > 0 else None
    return code


def _fail_account(username: str, reason: str, processed_counter) -> None:
    """Аккаунт не сделан: итог, в конец очереди, счётчик прохода."""
    _record_result(username, False, 0, reason)
    accounts_mod.rotate_to_end(username)
    _worker_clear(username)
    next(processed_counter)


def _ban_account(username: str, reason: str, processed_counter, removed: int = 0) -> None:
    """Аккаунт забанен/удалён у TikTok: убираем из accounts.json (в banned.json),
    итог отдельной категорией, НЕ в конец очереди — его больше нет. Круговая
    кампания на следующем круге его уже не увидит. Зовётся сразу после входа в
    том же потоке: код отказа (signin.last_ban_code) решает, оставить ли сессию —
    приостановленному её не сносим."""
    keep = signin.last_ban_code() in signin.KEEP_SESSION_CODES
    try:
        accounts_mod.mark_banned(username, reason, keep_session=keep)
    except OSError as exc:
        print("[campaign] %s: не удалось отключить забаненный аккаунт: %s"
              % (username, exc))
    eventlog.say("аккаунт забанен, отключён: %s" % reason, "err", username, "campaign")
    _record_result(username, False, 0, reason, banned=True, removed=removed)
    _worker_clear(username)
    next(processed_counter)


def _pause_account(username: str) -> None:
    """Следующий круг не снимает отказ защищённой операции этого аккаунта."""
    with _state_lock:
        if username not in _state["paused_accounts"]:
            _state["paused_accounts"].append(username)


def _account_trouble(final: dict) -> bool:
    """Пост не вышел по причине, за которой может стоять сам аккаунт, а не сеть.

    Приостановку (1091) и бан (1011) TikTok называет только на входе, а при живой
    сессии кампания не входит — публикация просто не выходит. Сеть, прокси и
    остановка пользователем к аккаунту отношения не имеют: по ним вход не
    проверяем, иначе каждый сбой прокси стоил бы лишнего входа."""
    if final.get("posts_done") or final.get("no_proxy"):
        return False
    last = final.get("last_result") or {}
    if final.get("stop_account") or batch_publish.publication_stops_account(last):
        return False
    return not (last.get("network") or last.get("verdict") == "transient")


def _read_notices(username: str, held) -> dict:
    """Уведомления аккаунта: снятые за нарушение правил посты видно ЗАРАНЕЕ —
    ошибка входа 1011 сообщает о беде только когда аккаунт уже забанен
    (the regression checks). Читаем ДО чистки и залива: аккаунт с историей
    нарушений должен быть виден в отчёте, даже если дальше он сорвётся.

    Чтение аккаунт не меняет (is_mark_read всегда 0), а сбой чтения не валит
    аккаунт: уведомления — диагностика, прогон из-за них не останавливается.
    Кому сказать о сбое — решает вызывающий: здесь только чтение."""
    _worker_set(username, "notices")
    try:
        from . import cloud
        return cloud.notices(username, held.url)
    except Exception as exc:  # noqa: BLE001 — диагностика не должна мешать заливу
        return {"removed": 0, "items": [], "more": False,
                "error": "%s: %s" % (type(exc).__name__, exc)}


# шаги воркера — человеческие подписи для UI (map в app.js campStepText)
def _worker_run(acc, slots, caption, title, min_delay_ms, max_delay_ms,
                posts_per_account, limit, processed_counter,
                delete_before=False, creatives="copies",
                keep_photos=False, media="photo") -> None:
    """Обработка одного аккаунта одним воркером пула.

    acc — полная запись accounts.json (секреты только здесь, в state не
    попадают). processed_counter — thread-safe счётчик сделанных аккаунтов
    (itertools-подобный, см. _run_campaign). Прокси аккаунт арендует у
    proxy_pool на всё время работы — наименее занятый живой."""
    username = acc.get("username")
    if _stop_requested():
        # проход остановили, пока аккаунт ждал в очереди пула: его не трогаем
        # вовсе — ни входа, ни итога «не вышло»
        return
    held = None
    try:
        print("[campaign] %s: взят в работу" % username)
        held = _take_proxy(username)
        proxy = held.url
        if proxy:
            print("[campaign] %s -> прокси %s" % (username, proxy_pool.short(proxy)))
        # ротационный прокси: перед каждым аккаунтом просим у провайдера
        # новый IP по его ссылке. Ссылка меняет IP на весь порт, поэтому
        # ротация одной ссылки идёт по одному и не чаще cooldown (см.
        # modules/proxies.py) — воркеры на одном порту ждут друг друга.
        entry = proxies_mod.entry_for(proxy) if proxy else None
        if entry is not None and entry.rotate_url:
            _worker_set(username, "rotate")
            rot = proxies_mod.rotate_for(entry, log=eventlog.teller(username, "proxy"))
            if not rot.get("ok"):
                print("[campaign] %s: сменить IP не вышло (%s) — идём "
                      "на старом" % (username, rot.get("reason") or "?"))

        _worker_set(username, "login")

        def check_step(p):
            from . import cloud
            res = cloud.session_check(username, p)
            terminal = res.get("stop_account") or res.get("verdict") == "unknown"
            return res, bool(res.get("network")) and not terminal

        # сбой сети на проверке ничего не говорит о сессии: входить заново из-за
        # него нельзя — пересаживаемся на другой прокси и проверяем ещё раз
        alive, network = _net_retry(check_step, held, username)
        if alive.get("stop_account") or alive.get("verdict") == "unknown":
            reason = alive.get("error") or "Проверка сессии не подтверждена"
            _pause_account(username)
            eventlog.say(reason, "err", username, "campaign")
            _fail_account(username, reason, processed_counter)
            return
        if network:
            reason = "сессия не проверена: " + humanize.network(alive.get("error") or "")
            eventlog.say(reason, "err", username, "campaign")
            _fail_account(username, reason, processed_counter)
            return
        if alive.get("alive"):
            print("[campaign] %s: сессия жива, вход не нужен" % username)
        else:
            _worker_set(username, "login")

            # итог входа («вход выполнен» / «вход не удался: причина») signin.run
            # пишет в ленту сам. Вход арендует прокси из СВОЕЙ группы; аренду
            # публикации сюда не передаём, иначе разделение групп теряет смысл.
            ok = signin.run(username, tee=False)
            if not ok:
                _pause_account(username)
                # НЕ останавливаем кампанию — пропускаем аккаунт: одна
                # проблема не должна рушить прогон по остальным.
                reason = signin.last_reason() or "вход не удался"
                # аккаунт удалён/забанен у TikTok — отключаем его насовсем,
                # чтобы не входить в него каждый круг впустую
                if signin.last_banned():
                    _ban_account(username, reason, processed_counter)
                    return
                _fail_account(username, "вход не удался: " + reason, processed_counter)
                return

        # что с аккаунтом было ДО нас: снятые за нарушение правил посты
        # (одно чтение уведомлений, аккаунт не меняется)
        notices = _read_notices(username, held)
        removed = notices.get("removed") or 0
        if notices.get("error"):
            print("[campaign] %s: уведомления не прочитались: %s"
                  % (username, notices["error"]))
        elif removed:
            eventlog.say("снято за нарушение правил: %d" % removed, "err",
                         username, "notice")

        to_delete = resolve_delete_count(delete_before, posts_per_account)
        cleanup_blocked = None  # причина, по которой заливать поверх нельзя
        if to_delete and not _stop_requested():
            # сколько именно — задаёт настройка кампании: столько же, сколько
            # публикуем, своё число или вообще все посты аккаунта
            _worker_set(username, "cleanup")
            # аккаунт, который прямо сейчас чистят вручную, не трогаем: двое
            # на одной сессии пишут её наперебой
            _taken, busy = purge.claim([username])
            if busy:
                cleanup_blocked = ("прошлые посты не удалены: аккаунт сейчас "
                                   "чистится вручную")
            else:
                try:
                    res = purge.run_one(username, held.url, to_delete)
                    if res["total"]:
                        eventlog.say("удалено прошлых постов: %d из %d"
                                     % (res["deleted"], res["total"]),
                                     "ok" if res["deleted"] == res["total"] else "warn",
                                     username, "delete")
                    if res["failed"]:
                        cleanup_blocked = ("прошлые посты не удалились: "
                                           "%d из %d на месте"
                                           % (len(res["failed"]), res["total"]))
                except Exception as exc:  # noqa: BLE001 — но залив без чистки не запускаем
                    if getattr(exc, "stop_account", False):
                        _pause_account(username)
                    print("[campaign] %s: удалить прошлые посты не вышло (%s: %s)"
                          % (username, type(exc).__name__, exc))
                    cleanup_blocked = "прошлые посты не удалены: %s" % humanize.error(exc)
                finally:
                    purge.release(username)

        if cleanup_blocked:
            # пользователь велел снести старые посты — заливать поверх
            # неудалённых нельзя: аккаунт помечается неуспешным и уходит
            # в конец очереди, прогон идёт дальше без него
            print("[campaign] %s: %s — заливка отменена"
                  % (username, cleanup_blocked))
            eventlog.say(cleanup_blocked + " — заливка отменена", "err",
                         username, "delete")
            _record_result(username, False, 0, cleanup_blocked)
            accounts_mod.rotate_to_end(username)
            _worker_clear(username)
            next(processed_counter)
            return

        _worker_set(username, "publishing")
        # Аренда уходит в батч. После начала отправки post неизвестный исход
        # останавливает аккаунт, без повторного post через другой прокси.
        worker = batch_publish.BatchWorker(
            slots, caption, title, min_delay_ms, max_delay_ms,
            username, limit, username=username, proxy=held.url or None,
            creatives=creatives, keep_photos=keep_photos, lease=held,
            media=media)
        worker.start()

        while True:
            if _stop_requested():
                worker.request_stop()
            st = worker.get_status()
            _worker_set(username, "wait_proxy" if st.get("waiting_proxy") else "publishing",
                        st.get("posts_done") or 0)
            if (st["posts_done"] >= posts_per_account
                    and st["status"] in ("running", "stopping")):
                worker.request_stop()
            if st["status"] not in ("running", "stopping"):
                break
            time.sleep(0.5)

        final = worker.get_status()
        paused = final.get("stop_account") or batch_publish.publication_stops_account(
            final.get("last_result") or {})
        if paused:
            _pause_account(username)
        died = final.get("proxy_died")
        if died and not final["posts_done"] and not to_delete and not paused:
            # прокси умер до первого поста, аккаунт не менялся — его доделает
            # другой поток, этот встаёт (настройка «прокси умер»)
            raise proxy_pool.ProxyDied(died)
        if final.get("no_proxy") and not _stop_requested():
            # воркер публикации не дождался ни одного живого прокси — стоп
            # всему проходу, как у остальных шагов
            _abort(_NO_PROXY_ABORT)
        # Ни одного поста, и виноват не сеть: у аккаунта могла быть живая сессия,
        # поэтому вход не выполнялся и приостановку (1091) кампания ещё не видела.
        # Спрашиваем TikTok входом: ответил баном — аккаунт уходит из списка, как
        # забаненный; нет — остаётся «не пролитым» и попробуется в следующий раз.
        if _account_trouble(final) and not _stop_requested():
            _worker_set(username, "login")

            print("[campaign] %s: ни одного поста — проверяю аккаунт входом" % username)
            if not signin.run(username, tee=False):
                _pause_account(username)
            if signin.last_banned():
                reason = signin.last_reason() or "аккаунт больше не работает"
                print("[campaign] %s: аккаунт не работает — %s" % (username, reason))
                _ban_account(username, reason, processed_counter, removed=removed)
                return
        print("[campaign] %s: готово, постов %d%s" % (
            username, final["posts_done"],
            " — " + final["stop_reason"] if final.get("stop_reason") else ""))
        # причину остановки (если пост не вышел) воркер уже написал в ленту
        # сам — здесь только счёт
        eventlog.say("готово, постов: %d" % final["posts_done"],
                     "ok" if final["posts_done"] else "warn", username, "campaign")
        _record_result(username, final["posts_done"] > 0, final["posts_done"],
                      final.get("stop_reason") or "", removed=removed)
        accounts_mod.rotate_to_end(username)
        next(processed_counter)
        if died:
            # посты уже шли — аккаунт посчитан с тем, что успел; поток встаёт
            raise proxy_pool.ProxyDied(died, requeue=False)
    except proxy_pool.ProxyDied:
        raise  # поток встаёт — решает цикл потока (_run_one_pass)
    except proxy_pool.NoAliveProxy:
        # живых прокси так и не появилось: проход уже остановлен (_wait_alive),
        # аккаунт не трогали — провалом его не считаем
        print("[campaign] %s: отложен — нет живых прокси" % username)
    except Exception as exc:  # noqa: BLE001 — один воркер не должен ронять остальных
        import traceback
        print("[campaign] %s: %s: %s" % (username, type(exc).__name__, exc))
        print(traceback.format_exc().rstrip())
        reason = humanize.error(exc)
        eventlog.say("аккаунт пропущен: %s" % reason, "err", username, "campaign")
        _record_result(username, False, 0, reason)
        accounts_mod.rotate_to_end(username)
        next(processed_counter)
    finally:
        if held is not None:
            held.release()
        _worker_clear(username)


class _Counter:
    """thread-safe счётчик сделанных аккаунтов; next() возвращает новый итог."""

    def __init__(self, start: int):
        self._value = start
        self._lock = threading.Lock()

    def __next__(self) -> int:
        with self._lock:
            self._value += 1
            value = self._value
        _advance(value)
        return value


def _begin_round(round_no: int) -> None:
    """Готовит состояние к новому кругу круговой кампании: чистит итоги и
    очередь прошлого круга, снимает флаги остановки/аборта (в паузе между
    кругами их мог поставить аборт, а не пользователь — пользовательскую
    остановку цикл ловит раньше и до сюда не доходит), возвращает статус
    running. started_at не трогаем — это старт всей кампании, не круга."""
    with _state_lock:
        _state["status"] = "running"
        _state["round"] = round_no
        _state["results"] = []
        _state["workers"] = []
        _state["queued"] = []
        _state["accounts_done"] = 0
        _state["accounts_total"] = 0
        _state["stop_requested"] = False
        _state["abort_reason"] = None
        _state["next_run_at"] = None
        _state["updated_at"] = _now()
    _pulse()


def _clear_stop_flags() -> None:
    """Снять флаги остановки/аборта — круговая кампания продолжается новым
    кругом, а не завершается. Пользовательскую остановку цикл ловит до вызова
    этого, так что здесь гасится только аборт (нет живых прокси)."""
    with _state_lock:
        _state["stop_requested"] = False
        _state["abort_reason"] = None
        _state["updated_at"] = _now()


def _human_wait(sec: int) -> str:
    """Секунды -> «4 ч 30 мин» / «45 мин» / «30 с» для лога паузы между кругами."""
    sec = int(sec)
    if sec >= 3600:
        h, m = sec // 3600, (sec % 3600) // 60
        return "%d ч %d мин" % (h, m) if m else "%d ч" % h
    if sec >= 60:
        m, s = sec // 60, sec % 60
        return "%d мин %d с" % (m, s) if s else "%d мин" % m
    return "%d с" % sec


def _wait_next_round(delay_sec: int) -> bool:
    """Пауза между кругами: статус "waiting", ждём delay_sec, просыпаемся на
    остановку. True — дождались (пора в новый круг), False — пользователь
    остановил кампанию во время паузы."""
    target = time.time() + delay_sec
    with _state_lock:
        _state["status"] = "waiting"
        _state["workers"] = []
        _state["next_run_at"] = datetime.fromtimestamp(target).isoformat()
        _state["updated_at"] = _now()
    _pulse()
    while time.time() < target:
        if _stop_requested():
            return False
        time.sleep(0.5)
    return not _stop_requested()


# коды итога одного круга (для цикла _run_campaign)
_PASS_RAN = "ran"          # круг отработал (флаги stop/abort смотрит цикл)
_PASS_NO_PROXY = "no_proxy"  # предпроверка: ни один прокси не отвечает
_PASS_EMPTY = "empty"      # ни одного аккаунта в очереди


def _run_one_pass(slots, caption, title, min_delay_ms, max_delay_ms,
                  posts_per_account, limit, threads, delete_before,
                  creatives, keep_photos, accounts, media="photo") -> str:
    """Один проход по очереди аккаунтов (пул из threads воркеров). Возвращает
    код итога; терминальное решение (finish/waiting) принимает _run_campaign
    по коду и флагам состояния. _finish отсюда НЕ зовётся — иначе круговой
    цикл не смог бы продолжиться."""
    # прокси проверяются до прохода: мёртвые в выбор не попадут, а без единого
    # живого проход не начинается — иначе каждый аккаунт очереди честно
    # провалился бы на мёртвом прокси
    proxies = proxy_pool.configured("publish")
    if proxies:
        marks = proxy_pool.check_all(proxies)
        alive = sum(1 for m in marks if m["state"] == "ok")
        if not alive:
            return _PASS_NO_PROXY
        eventlog.say("прокси: живых %d из %d" % (alive, len(proxies)),
                     "ok" if alive == len(proxies) else "warn", source="proxy")

    # фото, застрявшие в захвате после прошлого запуска, возвращаем в очередь
    # один раз на проход — до старта воркеров (см. photo_source)
    from . import photo_source
    photo_source.release_stale(slots)

    queue = [accounts_mod.load_account(a["username"])
             for a in accounts_mod.list_accounts()]
    # проход по выбранным: сохраняем порядок списка, который прислал UI
    # (порядок выделения), незнакомые имена молча отбрасываем — морда шлёт их
    # из того же списка аккаунтов, расхождение означает лишь параллельное удаление
    if accounts:
        wanted = [str(u).lstrip("@") for u in accounts if isinstance(u, str)]
        by_name = {q["username"]: q for q in queue if q}
        queue = [by_name[u] for u in wanted if u in by_name]
    # Новый круг не доказывает, что неизвестный post не создан или challenge
    # снят. Исключение действует до новой команды start_campaign пользователя.
    with _state_lock:
        paused = {str(u).lstrip("@").casefold() for u in _state["paused_accounts"]}
    queue = [q for q in queue if q and q["username"].lstrip("@").casefold() not in paused]
    total = len(queue)
    with _state_lock:
        _state["accounts_total"] = total
        # вся очередь прохода: UI ставит спиннеры на все строки сразу, а не
        # только на тех, за кого уже взялись воркеры
        _state["queued"] = [q["username"] for q in queue if q]
        _state["updated_at"] = _now()
    _pulse()

    if total == 0:
        return _PASS_EMPTY

    counter = _Counter(0)
    if threads <= 1:
        workers = 1  # последовательный режим: строго по одному, как раньше
    else:
        workers = min(threads, total)
    eventlog.say("публикация запущена: аккаунтов %d, потоков %d" % (total, workers),
                 "", source="campaign")

    # Потоки сами берут аккаунты из общей очереди. Прокси поток арендует,
    # когда дойдёт до аккаунта: к тому времени часть списка могла умереть,
    # ожить или освободиться. Поток, чей прокси умер при настройке «остановить
    # поток» (proxy_pool.ProxyDied), выходит; нетронутый аккаунт возвращается в
    # начало очереди. Свободный поток не уходит, пока другие заняты: кто-то из
    # них может вернуть аккаунт.
    pending = deque(queue)
    cond = threading.Condition()
    busy, alive = 0, workers

    def thread_loop():
        nonlocal busy, alive
        while True:
            with cond:
                while not pending and busy and not _stop_requested():
                    cond.wait(1)
                if not pending or _stop_requested():
                    alive -= 1
                    cond.notify_all()
                    return
                acc = pending.popleft()
                busy += 1
            died = None
            try:
                _worker_run(acc, slots, caption, title, min_delay_ms, max_delay_ms,
                            posts_per_account, limit, counter, delete_before,
                            creatives, keep_photos, media)
            except proxy_pool.ProxyDied as exc:
                died = exc
            with cond:
                busy -= 1
                if died is not None:
                    if died.requeue:
                        pending.appendleft(acc)
                    alive -= 1
                    orphaned = not alive and bool(pending)
                cond.notify_all()
            if died is not None:
                print("[campaign] %s: %s" % (acc.get("username"), died))
                eventlog.say(str(died), "warn", acc.get("username"), "campaign")
                if orphaned and not _stop_requested():
                    _abort(_ALL_THREADS_STOPPED)
                return

    pool = [threading.Thread(target=thread_loop, daemon=True,
                             name="campaign-%d" % (i + 1)) for i in range(workers)]
    for t in pool:
        t.start()
    # ждём все потоки (request_stop уже пометил живых — они досят текущий пост
    # и выходят)
    for t in pool:
        t.join()
    return _PASS_RAN


def _run_campaign(slots, caption, title, min_delay_ms, max_delay_ms,
                  posts_per_account, limit, threads, delete_before=False,
                  creatives="copies", keep_photos=False, accounts=None,
                  repeat=False, repeat_min_sec=0, repeat_max_sec=0,
                  media="photo") -> None:
    """Рабочий цикл кампании — фоновый daemon-поток. Один проход по очереди
    аккаунтов; при repeat — круг за кругом с паузой [repeat_min_sec,
    repeat_max_sec] между ними, пока пользователь не остановит.

    accounts — проход только по этим username (None — по всем, как раньше).
    Один проход (repeat=False) сохраняет прежнее поведение до буквы, включая
    тексты завершающих событий."""
    empty_reason = ("нет ни одного аккаунта — добавьте в разделе «Аккаунты»"
                    if not accounts else
                    "ни один из выбранных аккаунтов не найден — список устарел")
    try:
        round_no = 0
        while True:
            round_no += 1
            if round_no > 1:
                _begin_round(round_no)
            else:
                with _state_lock:
                    _state["round"] = 1

            code = _run_one_pass(slots, caption, title, min_delay_ms, max_delay_ms,
                                 posts_per_account, limit, threads, delete_before,
                                 creatives, keep_photos, accounts, media)

            with _state_lock:
                stop_requested = _state["stop_requested"]
                abort_reason = _state["abort_reason"]
            # пользовательская остановка главнее всего — завершаемся сразу
            if stop_requested and not abort_reason:
                _finish("остановлено пользователем")
                return

            # чем закончился круг и что писать в лог/финиш
            if code == _PASS_NO_PROXY:
                if not repeat:
                    _finish(proxy_pool.NO_ALIVE, is_error=True)
                    return
                eventlog.say(proxy_pool.NO_ALIVE, "warn", source="campaign")
            elif code == _PASS_EMPTY:
                if not repeat:
                    _finish(empty_reason)
                    return
                eventlog.say(empty_reason, "warn", source="campaign")
            elif abort_reason:
                if not repeat:
                    _finish(abort_reason, is_error=True)
                    return
                eventlog.say(abort_reason, "warn", source="campaign")
            else:
                if not repeat:
                    _finish("публикация завершена")
                    return
                with _state_lock:
                    _state["rounds_done"] += 1
                    done = _state["rounds_done"]
                    results = list(_state["results"])
                posts = sum(r["posts_done"] for r in results)
                eventlog.say("круг %d завершён: постов %d" % (done, posts),
                             "ok" if posts else "warn", source="campaign")

            # repeat: снимаем аборт/остановку (пользовательскую поймали выше) и
            # уходим в паузу до следующего круга
            _clear_stop_flags()
            delay = random.randint(repeat_min_sec, repeat_max_sec)
            eventlog.say("следующий круг через %s" % _human_wait(delay),
                         "", source="campaign")
            if not _wait_next_round(delay):
                _finish("остановлено пользователем")
                return
    except Exception as exc:  # noqa: BLE001 — неожиданная ошибка не должна ронять поток молча
        import traceback
        print(f"[campaign] {type(exc).__name__}: {exc}")
        print(traceback.format_exc().rstrip())
        _finish(humanize.error(exc), is_error=True)
    finally:
        _run_lock.release()
