"""Client publication queue and progress reporting."""

import random
import threading
import time
from datetime import datetime
from pathlib import Path

from . import eventlog, humanize, photo_source, proxy_pool


class BatchAlreadyRunningError(RuntimeError):
    """Батч уже выполняется — start_batch не может запустить второй параллельно."""


def _now() -> str:
    return datetime.now().isoformat()


# Сколько раз загрузка до отправки post может сменить отказавший прокси.
_MAX_PROXY_RECOVERIES = 3

# unique — каждому посту своё фото; copies — одно фото на прогон аккаунта, у
# каждого поста своя уникализированная копия; single — одна копия на все посты
CREATIVES = ("unique", "copies", "single")


def publication_stops_account(result: dict) -> bool:
    """Неизвестный исход или запрет платформы требует проверки пользователя."""
    return bool(result) and (
        result.get("stop_account") is True or result.get("state_saved") is False
        or bool(result.get("network"))
        or result.get("verdict") in ("unknown", "risk_block", "transient", "error"))


def upload_stops_account(exc: Exception) -> bool:
    """Обёртка ошибки файла не снимает запрет следующей сетевой операции."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if getattr(exc, "stop_account", False) or getattr(exc, "outcome_unknown", False):
            return True
        exc = exc.__cause__ or exc.__context__
    return False


class BatchWorker:
    """Один батч публикаций по одному аккаунту.

    start() поднимает фоновый daemon-поток и сразу возвращает снапшот
    статуса; дальше воркер опрашивается через get_status()/request_stop().
    get_status() можно звать из любых потоков (состояние под self._lock).

    username/proxy — чья это сессия и через какой IP она ходит (глобальные
    config.default_account/config.proxy не читаются — это и позволяет
    параллельным воркерам кампании не путать друг другу аккаунты и IP).
    """

    # Порядковый номер воркера в процессе: даёт каждому свою стартовую
    # позицию в листинге слота. Иначе все параллельные воркеры хватают один
    # и тот же первый файл, проигравшие уходят на новый круг, и фото уже
    # загруженных слотов возвращаются — лишний трафик на пустом месте.
    _seq = 0
    _seq_lock = threading.Lock()

    def __init__(self, slots, caption, title, min_delay_ms, max_delay_ms,
                 account, limit, username=None, proxy=None,
                 creatives="copies", keep_photos=False, lease=None, media="photo",
                 own_lease=False):
        with BatchWorker._seq_lock:
            BatchWorker._seq += 1
            self._pick_offset = BatchWorker._seq - 1
        self._media = media if media in photo_source.MEDIA else "photo"
        self._word = photo_source.MEDIA_WORD[self._media]
        # одинаковые креативы: комплект берётся один раз и уходит во все посты
        # аккаунта; разные — комплект на пост. Отправка post не повторяется.
        self._unique_creatives = creatives == "unique"
        self._keep = bool(keep_photos)
        self._copy_cache = {} if creatives == "single" else None
        # фото, удержанные на весь прогон (одинаковые креативы с удалением)
        self._held = []
        self._slots = [str(s) for s in slots]
        self._caption = caption
        self._title = title
        self._min_delay_ms = int(min_delay_ms)
        self._max_delay_ms = int(max_delay_ms)
        self._account = account
        self._username = username or account
        self._proxy = proxy
        # аренда прокси у proxy_pool (воркер кампании): до отправки post
        # возможна пересадка при однозначном отказе безопасной загрузки
        self._lease = lease
        self._own_lease = bool(own_lease)
        self._session = None
        self._recovered = 0
        self._limit = limit
        self._run_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._state = self._initial_state()
        self._state.update({
            "account": account,
            "slots": [str(s) for s in slots],
            "caption": caption,
            "title": title,
            "min_delay_ms": int(min_delay_ms),
            "max_delay_ms": int(max_delay_ms),
        })
        self._thread = None

    def _initial_state(self) -> dict:
        return {
            "status": "idle",
            "account": None,
            "slots": [],
            "caption": "",
            "title": "",
            "min_delay_ms": 0,
            "max_delay_ms": 0,
            "post_index": 0,
            "posts_done": 0,
            "files_deleted": 0,
            "current_post_files": [],
            "last_result": None,
            "stop_reason": None,
            "started_at": None,
            "finished_at": None,
            "updated_at": _now(),
            "stop_requested": False,
            "waiting_proxy": False,  # ждёт, пока оживёт хоть один прокси
            "no_proxy": False,       # не дождался — кампания остановит проход
            "proxy_died": "",        # прокси умер, настройка велит встать потоку
            "stop_account": False,   # до проверки результата не продолжать аккаунт
        }

    def start(self) -> dict:
        """Запускает воркер в фоновом daemon-потоке, возвращает снапшот статуса.

        Повторный вызов до завершения — BatchAlreadyRunningError (воркер
        не перезапускается поверх работающего)."""
        if not self._run_lock.acquire(blocking=False):
            raise BatchAlreadyRunningError("батч уже выполняется")
        with self._state_lock:
            self._state.update({"status": "running", "started_at": _now(),
                                "updated_at": _now()})
        self._thread = threading.Thread(target=self._thread_main, daemon=True)
        self._thread.start()
        return self.get_status()

    def _thread_main(self) -> None:
        """Страховка вокруг всего воркера, включая создание и прогрев сессии.

        Основной `_run` ловит ошибки рабочего цикла, но создание сессии стоит
        до его внутреннего try. Если оно сорвётся, аренда публикации всё равно
        должна освободиться, а статус — перестать висеть в running.
        """
        try:
            self._run()
        except Exception as exc:  # noqa: BLE001 — граница фонового потока
            import traceback
            print(f"[publish] {self._account}: {type(exc).__name__}: {exc}")
            print(traceback.format_exc().rstrip())
            self._fail(humanize.error(exc), is_error=True)
            if self._own_lease and self._lease is not None:
                self._lease.release()
            if self._run_lock.locked():
                self._run_lock.release()

    def get_status(self) -> dict:
        """Копия состояния под локом — безопасно из любых потоков."""
        with self._state_lock:
            return dict(self._state)

    def request_stop(self) -> dict:
        """Идемпотентна: если статус не running/stopping — просто возвращает
        текущий get_status(), это не ошибка. Иначе ставит флаг остановки и
        статус "stopping", возвращает get_status() — реальная остановка
        произойдёт асинхронно, между постами/во время паузы."""
        with self._state_lock:
            if self._state["status"] not in ("running", "stopping"):
                return dict(self._state)
            self._state["status"] = "stopping"
            self._state["stop_requested"] = True
            self._state["updated_at"] = _now()
            return dict(self._state)

    def _finish(self, reason: str, is_error: bool = False) -> None:
        with self._state_lock:
            self._state["status"] = "error" if is_error else "stopped"
            self._state["stop_reason"] = reason
            self._state["finished_at"] = _now()
            self._state["updated_at"] = _now()

    def _fail(self, reason: str, is_error: bool = False) -> None:
        """Остановка из-за проблемы: причина — и в итог, и в ленту событий."""
        eventlog.say(reason, "err", self._account, "publish")
        self._finish(reason, is_error)

    def _pick_kept(self) -> list:
        """По фото из каждого слота по кругу, без захвата — фото остаются в папках."""
        paths = []
        for index, folder in enumerate(self._slots):
            path = photo_source.pick_kept(folder, self._media)
            if path is None:
                raise FileNotFoundError(
                    f"{photo_source.slot_name(index, folder, self._media)} пуста")
            paths.append(path)
        return paths

    def _interruptible_sleep(self, delay_ms: float) -> bool:
        """Спит суммарно delay_ms миллисекунд чанками ~0.5с, проверяя
        stop_requested после каждого чанка. Возвращает True, если сон был
        прерван флагом остановки раньше срока."""
        remaining = delay_ms / 1000.0
        while remaining > 0:
            chunk = min(0.5, remaining)
            time.sleep(chunk)
            remaining -= chunk
            with self._state_lock:
                if self._state["stop_requested"]:
                    return True
        return False

    def _stopping(self) -> bool:
        with self._state_lock:
            return self._state["stop_requested"]

    def _recover_proxy(self) -> bool:
        """Загрузка до отправки post сорвалась на сети — виноват ли прокси.

        Сессия уже сама пересаживалась по ходу повторов (proxy_pool.bind),
        здесь — случай, когда все повторы кончились. Прокси проверяется тут
        же. Жив — False: сбой не его, пост проваливается как раньше. Мёртв —
        пересадка на другой живой; другого нет — ожидание, пока оживёт хоть
        один (до proxy_pool.WAIT_SEC). True — сессия смотрит в живой прокси,
        загрузку можно продолжить. Не дождались — False и отметка no_proxy:
        кампания остановит весь проход. Настройка велит не пересаживать, а
        останавливать поток, — False и отметка proxy_died (proxy_pool.reseat)."""
        held = self._lease
        if held is None or not held.url or self._recovered >= _MAX_PROXY_RECOVERIES:
            return False
        if proxy_pool.check(held.url)["state"] != "dead":
            return False
        failed = held.url
        try:
            alive = proxy_pool.reseat(held, stop=self._stopping,
                                      waiting=self._set_waiting, dead=True)
        except proxy_pool.ProxyDied:
            with self._state_lock:
                self._state["proxy_died"] = failed
            return False
        if not alive:
            if not self._stopping():
                with self._state_lock:
                    self._state["no_proxy"] = True
            return False
        self._recovered += 1
        from . import proxies
        proxy = proxies.remote_dns(held.url)
        self._session.proxies = {"all": proxy}
        print(f"[publish] {self._account}: прокси {proxy_pool.short(failed)} "
              f"не отвечает — загрузка через {proxy_pool.short(held.url)}")
        return True

    def _via(self):
        """(аккаунт, текущий прокси) — для вызовов нашего сервера
        (modules/cloud.py)."""
        lease_url = self._lease.url if self._lease is not None else None
        return (self._username, lease_url or self._proxy)

    def _set_waiting(self, on: bool) -> None:
        with self._state_lock:
            self._state["waiting_proxy"] = on

    def _proxy_gone(self) -> str:
        """Почему пост не пробуем заново через другой прокси: живых не
        дождались или поток встаёт вместе с прокси. "" — прокси ни при чём."""
        with self._state_lock:
            if self._state["no_proxy"]:
                return proxy_pool.NO_ALIVE
            died = self._state["proxy_died"]
        return str(proxy_pool.ProxyDied(died)) if died else ""

    def _publish_via_server(self, via, items) -> dict:
        """Пост из файлов, залитых через сервер. Отказ самого сервера — тот же
        вид ответа, что у отказа TikTok: вызывающему разницы нет."""
        from . import cloud, remote
        try:
            if self._media == "video":
                return cloud.publish_video_item(*via, items[0], self._caption)
            return cloud.publish_photo_items(*via, items, self._caption, self._title)
        except Exception as exc:  # noqa: BLE001 — защищённый вызов мог уже завершиться
            # Ответ сервера мог потеряться после создания поста. Диагностика
            # сети не разрешает ещё одну отправку через другой прокси.
            return {"ok": False, "verdict": "unknown", "code": exc.status if isinstance(exc, remote.RemoteError) else None,
                    "message": "Результат публикации не подтверждён. Проверьте посты перед повтором.",
                    "network": False, "stop_account": True, "retriable": False}

    def _run(self) -> None:
        """Рабочий цикл воркера — фоновый daemon-поток."""
        from curl_cffi import requests
        from . import client_device, proxies
        session = requests.Session(impersonate=client_device.IMPERSONATE)
        session.proxies = {"all": proxies.remote_dns(self._proxy)} if self._proxy else {}
        # Binding используется до отправки post. Ответ начатой публикации
        # не разрешает повторный post или смену прокси ради его повтора.
        proxy_pool.bind(session, self._lease)
        self._session = session
        # Разогрев сессии (msToken, куки бот-менеджера) делает наш сервер сам.
        post_index = 0
        shared = []   # комплект на все посты аккаунта (одинаковые креативы)
        try:
            if not self._unique_creatives:
                # одинаковые креативы: комплект берётся один раз и уходит во
                # все посты этого аккаунта. Захват до первого поста — он же и
                # разводит параллельные воркеры: удержанные файлы выпадают из
                # листинга, соседям достанутся следующие
                try:
                    if self._keep:
                        shared = self._pick_kept()
                    else:
                        self._held = photo_source.hold_slot_photos(self._slots,
                                                                   self._media)
                        shared = list(self._held)
                except FileNotFoundError as exc:
                    self._fail(f"{exc} — публикация аккаунта остановлена, "
                               f"чтобы не выложить неполный пост")
                    return
                print(f"[batch] {self._account}: комплект на прогон — "
                      + ", ".join(photo_source.original_name(p) or p.name
                                  for p in shared))

            while True:
                with self._state_lock:
                    stop_requested = self._state["stop_requested"]
                if stop_requested:
                    self._finish("остановлено пользователем")
                    return

                if post_index >= self._limit:
                    self._finish("достигнут лимит постов за проход")
                    return

                if self._unique_creatives:
                    listings = [photo_source.list_slot_photos(s, self._media)
                                for s in self._slots]
                    empty_idx = next((i for i, files in enumerate(listings) if not files), None)
                    if empty_idx is not None:
                        name = photo_source.slot_name(empty_idx, self._slots[empty_idx],
                                                      self._media)
                        self._fail(f"{name} пуста — публикация аккаунта остановлена, "
                                   f"чтобы не выложить неполный пост")
                        return

                if post_index > 0:
                    delay_ms = random.uniform(self._min_delay_ms, self._max_delay_ms)
                    stopped_during_pause = self._interruptible_sleep(delay_ms)
                    if stopped_during_pause:
                        self._finish("остановлено пользователем (во время паузы)")
                        return

                if self._unique_creatives and self._keep:
                    try:
                        paths = self._pick_kept()
                    except FileNotFoundError as exc:
                        self._fail(f"{exc} — публикация аккаунта остановлена, "
                                   f"чтобы не выложить неполный пост")
                        return
                elif self._unique_creatives:
                    # свой файл на воркера: смещение по номеру воркера, дальше
                    # по кругу — если файлов меньше, чем воркеров, часть всё
                    # равно сойдётся на одном, и это разрулит захват
                    paths = [listings[i][self._pick_offset % len(listings[i])]
                             for i in range(len(self._slots))]
                else:
                    # тот же комплект на каждый пост аккаунта; листинг
                    # перечитывать незачем — файлы уже выбраны
                    paths = list(shared)
                with self._state_lock:
                    self._state["post_index"] = post_index + 1
                    self._state["current_post_files"] = [str(p) for p in paths]
                    self._state["updated_at"] = _now()

                try:
                    via = self._via()
                    photos = photo_source.prepare_post_photos(
                        paths, session=session, username=self._username,
                        consume=self._unique_creatives and not self._keep,
                        cache=self._copy_cache, media=self._media,
                        via=via)
                except photo_source.PhotoClaimConflict:
                    # только режим разных креативов: выбранные файлы успел
                    # захватить параллельный воркер (слоты общие) — берём
                    # следующие по листингу, пост не потерян и не сделан
                    # дублём. Удержанный комплект уже наш, для него такого
                    # конфликта не бывает
                    continue
                except photo_source.PhotoConsumeError as exc:
                    # то, что успело уйти в TikTok, уже списано внутри
                    # prepare_post_photos (burn_photos) — доверие потрачено
                    print(f"[publish] {self._account}: TOS, "
                          f"{Path(exc.failed_path).name}: {exc}")
                    if upload_stops_account(exc):
                        with self._state_lock:
                            self._state["stop_account"] = True
                        self._fail("Загрузка остановлена. Проверьте аккаунт и результат перед повтором.")
                        return
                    network = "curl" in str(exc).lower()
                    if network and self._recover_proxy():
                        # пост ещё не отправлялся — заново через живой прокси,
                        # дубля не будет
                        continue
                    why = ((self._proxy_gone() or humanize.network(exc)) if network
                           else f"TikTok не принял загрузку {self._word}")
                    tail = "" if self._keep else (f". {self._word.capitalize()}, "
                                                  f"успевшие уйти в TikTok, списаны")
                    self._fail(f"пост №{post_index + 1} не опубликован: {why}{tail}")
                    return

                result = self._publish_via_server(via, photos)
                if (not isinstance(result, dict) or not isinstance(result.get("ok"), bool)
                        or (result.get("ok") and (result.get("verdict") != "ok" or not result.get("item_id")))):
                    result = {"ok": False, "verdict": "unknown", "code": None,
                              "message": "Сервер не подтвердил публикацию. Проверьте посты перед повтором.",
                              "stop_account": True, "network": False}
                stop_account = publication_stops_account(result)
                with self._state_lock:
                    self._state["last_result"] = result
                    self._state["stop_account"] = stop_account
                    self._state["updated_at"] = _now()

                if result["ok"]:
                    # пост вышел. В режиме разных креативов фото потрачены
                    # именно сейчас, в режиме одинаковых комплект держится
                    # дальше и спишется на выходе — commit_photos его не
                    # тронет (флаг keep), поэтому deleted тут будет 0
                    deleted = photo_source.commit_photos(photos)
                    with self._state_lock:
                        self._state["posts_done"] += 1
                        self._state["files_deleted"] += deleted
                        self._state["updated_at"] = _now()
                    post_index += 1
                    spent = (f"{self._word} остаются в папках" if self._keep
                             else f"{self._word}: {deleted}" if self._unique_creatives
                             else "комплект прогона")
                    print(f"[publish] {self._account}: пост №{post_index} опубликован "
                          f"({spent}, item_id={result.get('item_id') or '—'})")
                    eventlog.say(f"пост №{post_index} опубликован", "ok",
                                 self._account, "publish")
                    if stop_account:
                        self._fail("Пост создан. Проверьте аккаунт и сохранённый вход перед следующей публикацией.")
                        return
                    continue

                # код и сырой ответ — в подробности, в ленту — понятная причина
                print(f"[publish] {self._account}: пост №{post_index + 1} не вышел: "
                      f"{result['verdict']}, код {result.get('code')}: {result['message']}")
                why = ("Результат публикации не подтверждён. Проверьте посты перед новой отправкой"
                       if stop_account and result.get("verdict") in ("unknown", "transient", "error")
                       else humanize.verdict(result))

                if not self._unique_creatives:
                    tail = "" if self._keep else (". Комплект аккаунта списан — "
                                                  "он уже уходил в TikTok")
                    self._fail(f"пост №{post_index + 1} не подтверждён: {why}{tail}")
                    return

                # пост не вышел, но фото уже ушли на серверы TikTok — доверие
                # к ним потрачено, в папки они не возвращаются (burn_photos)
                burned = photo_source.burn_photos(photos)
                tail = "" if self._keep else (f". {self._word.capitalize()} уже ушли "
                                              f"в TikTok и списаны: {burned}")
                self._fail(f"пост №{post_index + 1} не подтверждён: {why}{tail}")
                return
        except Exception as exc:  # noqa: BLE001 — неожиданная ошибка не должна ронять поток молча
            import traceback
            print(f"[publish] {self._account}: {type(exc).__name__}: {exc}")
            print(traceback.format_exc().rstrip())
            self._fail(humanize.error(exc), is_error=True)
        finally:
            # удержанный на прогон комплект: если он хоть раз уходил в TikTok,
            # доверие к фото потрачено — списываем, иначе следующий запуск
            # зальёт засвеченное повторно. Если прогон закрыли до первой
            # загрузки, отдаём комплект назад в очередь — терять нечего
            if self._held:
                with self._state_lock:
                    uploaded = (self._state["post_index"] or 0) > 0
                if uploaded:
                    dropped = photo_source.release_held(self._held)
                    if dropped:
                        with self._state_lock:
                            self._state["files_deleted"] += dropped
                            self._state["updated_at"] = _now()
                        print(f"[batch] {self._account}: комплект прогона "
                              f"списан: {dropped}")
                else:
                    returned = photo_source.return_held(self._held)
                    if returned:
                        print(f"[batch] {self._account}: залива не было, "
                              f"комплект возвращён в папки: {returned}")
                self._held = []
            if self._own_lease and self._lease is not None:
                self._lease.release()
            self._run_lock.release()


# ── module-level фасад: «последний созданный» воркер ────────────────────────
# Для одиночной публикации из main.py (/api/batch/*): пользовательский путь
# один, второй батч до завершения первого — ошибка. Кампания-пул фасад НЕ
# использует, зовёт BatchWorker напрямую.

_last_worker = None
_last_lock = threading.Lock()


def start_batch(slots, caption, title, min_delay_ms, max_delay_ms, account, limit,
                username=None, proxy=None) -> dict:
    """Запускает новый батч (воркер) и сразу возвращает снапшот статуса
    (не ждёт первого поста).

    slots — список путей-папок (строки/Path), один слот на позицию карусели.
    caption/title — тексты поста (могут быть пустыми). min_delay_ms/
    max_delay_ms — целые >= 0, диапазон паузы между постами в миллисекундах;
    валидация диапазона — забота вызывающего (main.py), здесь не
    перепроверяется. account — имя аккаунта (для сессии/отчёта).
    username — чей jar (по умолчанию совпадает с account). Явный proxy
    используется как передан; без него батч арендует прокси из группы
    «Публикация». limit —
    максимум постов за этот запуск батча числом: передаётся параметром, а
    не берётся из config здесь — чтобы вся логика батча была тестируема
    без реального config.py. Без персистенции и без привязки к дням.

    Если батч уже выполняется (фасадный воркер жив) — бросает
    BatchAlreadyRunningError, ничего не меняя в состоянии.
    """
    global _last_worker

    # захваты от прошлого запуска (программу закрыли посреди поста) —
    # обратно в очередь, пока воркеров ещё нет: живые захваты трогать нельзя
    photo_source.release_stale(slots)

    with _last_lock:
        if _last_worker and _last_worker.get_status()["status"] in ("running", "stopping"):
            raise BatchAlreadyRunningError("батч уже выполняется")
        held = None
        if proxy is None:
            held = proxy_pool.lease(task="publish")
            proxy = held.url or None
        try:
            worker = BatchWorker(slots, caption, title, min_delay_ms, max_delay_ms,
                                 account, limit, username=username, proxy=proxy,
                                 lease=held, own_lease=held is not None)
        except Exception:
            if held is not None:
                held.release()
            raise
        _last_worker = worker
    try:
        return worker.start()
    except Exception:
        if held is not None:
            held.release()
        raise


def get_status() -> dict:
    """Статус последнего запущенного через фасад воркера (idle, если ещё
    никаких)."""
    with _last_lock:
        return _last_worker.get_status() if _last_worker else {
            "status": "idle", "account": None, "posts_done": 0}


def request_stop() -> dict:
    """Просит фасадный воркер остановиться (идемпотентно)."""
    with _last_lock:
        return _last_worker.request_stop() if _last_worker else {
            "status": "idle", "account": None, "posts_done": 0}
