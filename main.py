"""Local Nimbus HTTP API serving the desktop window and optional LAN access."""
import json
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UI_DIR = ROOT / "ui"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules import config  # noqa: E402

_MAX_BODY = 4 * 1024 * 1024  # 4 MiB
# фото в папку-слот приходит сырым телом: лимит свой, крупнее обычного
_MAX_UPLOAD = 64 * 1024 * 1024  # 64 MiB
# видео пишется на диск частями, в памяти не держится — потолок только от
# случайной ошибки (студия TikTok сама берёт до 30 ГБ)
_MAX_VIDEO_UPLOAD = 4 * 1024 * 1024 * 1024

# единицы паузы между кругами повторной публикации: множитель до секунд
_REPEAT_UNITS = {"min": 60, "hour": 3600}


def _repeat_seconds(value, unit) -> int:
    """«через N <единиц>» -> секунды. Мусор/ноль -> 0 (проверку валидного
    диапазона делает вызывающий)."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, n) * _REPEAT_UNITS.get(unit, 3600)

# Чистки постов (кто чистится, итоги) ведёт modules/purge.py; сюда приходит
# только итог каждой чистки — поправить числа студии в снимке.
def _studio_note_purge(username: str, result: dict) -> None:
    # Числа студии в снимке поправляем сразу: сколько постов удалено, чистка
    # уже знает, а ждать пересборки (TTL 90 с) значило бы показывать в таблице
    # число, которого на аккаунте больше нет. В сеть за этим не ходим и строку
    # подменяем целиком: читатель забирает копию набора под тем же замком и
    # может разбирать её уже без него.
    #
    # Итог чистки проверяем до арифметики: снимок подправляется ради удобства,
    # и уронить на нём уже удавшуюся чистку нельзя — исключение отсюда ушло бы
    # в общий обработчик и записало в журнал, что посты не удалились.
    deleted = result.get("deleted")
    if (result.get("error") or isinstance(deleted, bool)
            or not isinstance(deleted, int) or deleted <= 0):
        return
    with _studio_lock:
        row = _studio_cache.get(username)
        if isinstance(row, dict):
            # posts бывает None: _num в studio.py отдаёт None, когда счётчик не
            # пришёл или пришёл мусором. Пустое число считаем нулём; значение
            # другой породы (такого studio.counters не отдаёт) не трогаем —
            # ноль на его месте был бы выдуманным числом.
            current = row.get("posts") or 0
            if isinstance(current, int) and not isinstance(current, bool):
                _studio_cache[username] = dict(
                    row, posts=max(0, current - deleted))
    # Посты профиля — то же самое: по ним считаются «в тени» и просмотры, и
    # без этого после чистки у аккаунта с нулём постов оставались тени.
    try:
        from modules import profiles
        profiles.forget_recent(username, deleted)
    except Exception as exc:  # noqa: BLE001 — чистка уже удалась, снимок — удобство
        print("[purge] %s: посты профиля не поправлены (%s)" % (username, exc))

# Числа студии по аккаунтам (посты, подписчики, непросмотренные посетители):
# их отдаёт сам аккаунт по своим кукам, но и стоит это трёх запросов через
# прокси на каждый (профиль ради user_id, счётчики постов, подписчики; с уже
# известным user_id — двух) — на полсотни аккаунтов разом не собрать. Держим
# снимок в кэше, а сбор уводим в фон: запрос ответа не ждёт, морда
# «Аккаунтов» опрашивает раз в минуту и показывает то, что успело собраться.
# «Забыть», «Выйти», «Удалить»: галочка «Сменить устройство» в теле запроса.
# Без неё компьютер аккаунта сохраняется у сервера — не вышло, говорим так.
_DEVICE_NOT_KEPT = "компьютер аккаунта не сохранён (%s) — повторите или отметьте «Сменить устройство»"


def _new_device(body) -> bool:
    return isinstance(body, dict) and body.get("new_device") is True


_studio_lock = threading.Lock()
_studio_cache = {}    # username -> результат studio.counters()
_studio_at = 0.0      # когда снимок собран (time.monotonic)
_studio_busy = False  # сбор идёт прямо сейчас — второго не запускаем
# TTL чуть больше опроса морды (60 с): тогда новый сбор приходится не на
# каждый её запрос, а примерно на каждый второй, и прокси не молотит зря
_STUDIO_TTL = 90.0


def _studio_collect() -> dict:
    """Собрать числа студии со всех аккаунтов со входом.

    Аккаунт без сохранённого входа в набор не попадает — по кукам его не
    спросить. Ошибка одного аккаунта остальным не мешает: что не отдалось,
    просто не появляется в наборе, и морда оставит по нему числа профиля.

    Через прокси — обязательно, как и для остальных авторизованных запросов:
    с прямого IP студия отдаёт пустоту (шапка modules/studio.py говорит это
    про список постов, а счётчики проверены живьём только через прокси), а
    показать ноль вместо настоящего числа хуже, чем не показать ничего. Прокси
    выключены — значит, и собирать нечего.
    """
    from modules import accounts, cloud, proxy_pool
    names = [a["username"] for a in accounts.list_accounts()
             if a.get("has_session")]
    if not names:
        return {}
    try:
        held = proxy_pool.lease()
    except proxy_pool.NoAliveProxy as exc:
        print("[studio] числа не собраны: %s" % exc)
        return {}
    if not held.url:
        print("[studio] прокси выключены — числа студии не собираем")
        return {}
    out = {}
    try:
        for name in names:
            try:
                out[name] = cloud.studio(name, held.url, "counters")
            except Exception as exc:  # noqa: BLE001 — один аккаунт не рушит остальные
                print("[studio] %s: числа не отдались (%s: %s)"
                      % (name, type(exc).__name__, exc))
    finally:
        held.release()
    return out


def _studio_counters() -> dict:
    """Числа студии для UI: снимок из кэша, протухший кэш — сбор фоном.

    Ответ отдаётся сразу, не дожидаясь сети: сбор на десяток аккаунтов идёт
    дольше, чем морда готова ждать (у неё таймаут 20 с), и подвешенный запрос
    просто не дошёл бы. Пустой набор — тоже честный ответ.

    Тот же снимок отдаётся и когда фоновый поток не завёлся: без этого флаг
    «сбор идёт» остался бы поднятым навсегда, ручка залипла бы на старом
    снимке до перезапуска, а исключение вышло бы из обработчика запроса.
    """
    global _studio_busy
    with _studio_lock:
        if _studio_busy or time.monotonic() - _studio_at < _STUDIO_TTL:
            return dict(_studio_cache)
        _studio_busy = True  # под замком: два запроса разом сбор не запускают

    def work():
        global _studio_at, _studio_cache, _studio_busy
        try:
            out = _studio_collect()
            with _studio_lock:
                _studio_cache = out
                _studio_at = time.monotonic()
        finally:
            with _studio_lock:
                _studio_busy = False

    try:
        threading.Thread(target=work, daemon=True).start()
    except Exception as exc:  # noqa: BLE001 — поток ОС не дался: не залипаем
        print("[studio] сбор не запустился (%s: %s)" % (type(exc).__name__, exc))
        with _studio_lock:
            _studio_busy = False
    with _studio_lock:
        return dict(_studio_cache)

_STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml", ".ico": "image/x-icon", ".webp": "image/webp",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
}

# --- «схема в строке не названа» между запусками ----------------------------
#
# Разбор строки прокси помнит, называл ли схему человек (modules/proxies.py):
# от этого зависит, спрашивать ли у самого прокси его тип (needs_detect). В
# config уезжает канонический адрес, где подставленный http ничем не
# отличается от написанного, поэтому рядом со списком лежит отметка
# proxy_scheme_named: {адрес без логина и пароля: названа ли схема}. По ней
# старт (build_server) снова разбирает строки, которые писались без схемы, — и
# после перезапуска тип такой строки опять определяется работой, а не догадкой.
SCHEME_NAMED_KEY = "proxy_scheme_named"


def _restore_scheme_knowledge(cfg=None) -> int:
    """Снова сказать разбору прокси, какие строки писались без схемы.

    Знание «схему здесь не называли» живёт в памяти того процесса, который
    строку разбирал, и умирает вместе с ним: в config лежит канонический адрес,
    по которому подставленный http от написанного не отличить. Отметка
    SCHEME_NAMED_KEY рядом со списком его возвращает — строки без схемы снова
    проходят разбор, ровно тем же, каким их прошёл бы человек, вставивший их в
    разделе «Прокси». Возвращает число восстановленных строк (нужно пробе).

    Всё необязательное: нет файла, нет отметки, она чужая или битая — пусто и
    молча. Цена ошибки — лишний вопрос прокси о его типе, ронять из-за этого
    старт нечем."""
    from modules import proxies as proxies_mod
    cfg = config.load() if cfg is None else cfg
    named = cfg.get(SCHEME_NAMED_KEY)
    urls = cfg.get("proxies") or []
    if not isinstance(named, dict) or not isinstance(urls, list):
        return 0
    # что писал человек, знает канонический адрес без подставленной нами схемы
    lines = []
    for url in urls:
        if not isinstance(url, str) or "://" not in url:
            continue
        entry, err = proxies_mod.parse_line(url)
        if err or entry is None or named.get(entry.safe) is not False:
            continue
        lines.append(url.split("://", 1)[1])
    if lines:
        proxies_mod.parse_text("\n".join(lines))
    return len(lines)


# Адреса, которые принимают PUT (разбор — в do_PUT ниже). Список стоит здесь
# один раз: по нему же отвечают на незнакомый адрес, и текст ответа не отстаёт
# от кода, когда маршрутов становится больше.
_PUT_ROUTES = ("/api/config", "/api/proxies", "/api/settings", "/api/uniq",
               "/api/campaign/form", "/api/license")


class Handler(BaseHTTPRequestHandler):
    server_version = "TikTokWebAPI/1.0"
    protocol_version = "HTTP/1.1"
    # живой поток: снимок прогресса публикации не чаще раза в столько секунд
    CAMPAIGN_EVERY = 0.3
    # и пачка обновлённых профилей: глазу мгновенно, а тысяча аккаунтов не
    # превращается в тысячи сообщений и перерисовок списка
    PROFILES_EVERY = 0.05

    # --- инфраструктура ответов ---

    def handle_one_request(self):
        """Отметку «тело дочитано» сбрасываем на КАЖДЫЙ запрос: при keep-alive
        один и тот же обработчик обслуживает их подряд, и отметка от прошлого
        запроса заставила бы пропустить тело следующего."""
        self._body_done = False
        super().handle_one_request()

    def _json(self, obj, status: int = 200, headers=()):
        # тело запроса дочитываем ДО ответа, даже если обработчику оно не нужно:
        # иначе его остаток уедет в следующий запрос по тому же соединению
        self._drain_body()
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def _drain_body(self):
        """Прочитать и выбросить тело запроса, на который отвечаем не читая его.
        Тело крупнее обычного не вычитываем — закрываем соединение.

        Зовётся САМ из _json на каждый ответ, а не руками в каждом обработчике.
        Причина: соединение держится открытым (keep-alive), и непрочитанное
        тело разбирается как начало СЛЕДУЮЩЕГО запроса. Обработчики без тела
        («выйти», «остановить», «проверить прокси») отвечали, не читая, а фронт
        шлёт им `{}` — эти два байта и становились следующей строкой запроса:
        в логе `code 400, message Bad request syntax ('{}')`, и сбоил при этом
        совсем другой, ни в чём не повинный запрос.

        Повторный вызов безопасен: _read_json и этот помощник ставят отметку,
        и второй раз из сокета никто не читает."""
        if getattr(self, "_body_done", False):
            return
        self._body_done = True
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0:
            return
        if n > _MAX_BODY:
            self.close_connection = True
            return
        try:
            self.rfile.read(n)
        except OSError:
            self.close_connection = True

    # --- пароль на интерфейс (modules/auth.py) ---

    def _secure_link(self) -> bool:
        """Пришёл ли запрос по https (через обратный прокси) — от этого
        зависит флаг Secure у куки входа."""
        proto = (self.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip()
        return proto.lower() == "https"

    def _client_ip(self) -> str:
        """Адрес для счётчика неудачных попыток. Заголовкам прокси не верим:
        их подделывает кто угодно, и подбор пароля обошёл бы ограничение —
        за обратным прокси счётчик просто становится общим."""
        return str(self.client_address[0]) if self.client_address else "?"

    def _auth_ok(self) -> bool:
        from modules import auth
        if hasattr(self.server, "phone_parent") and not auth.enabled():
            return False
        return not auth.enabled() or auth.cookie_ok(self.headers.get("Cookie"))

    def _auth_required(self) -> bool:
        """Спрашивает ли сервер пароль с этого адреса. С самого компьютера —
        нет: оттуда ходит окно программы, а кто сидит за компьютером, и так
        у себя. С телефона и из сети — по паролю, если сервер его спрашивает
        (app.py собирает сервер с auth, только когда включён доступ с телефона)."""
        from modules import auth
        if hasattr(self.server, "phone_parent"):
            return True
        if self._client_ip() in ("127.0.0.1", "::1"):
            return False
        return bool(getattr(self.server, "require_auth", True)) and auth.enabled()

    def _foreign(self) -> bool:
        """Запрос пришёл не из окна программы и не с телефона, а с чужой
        страницы в браузере владельца. С 127.0.0.1 пароль не спрашивается,
        поэтому без этой проверки любой сайт мог отправить POST на
        127.0.0.1:8740 (удалить аккаунты), а подменой DNS — прочитать ответ
        (пароли из /api/accounts/secrets). Host должен быть IP-адресом,
        localhost или именем из настройки allowed_hosts (обратный прокси с
        доменом); Origin, если браузер его прислал, — тем же сервером."""
        import ipaddress
        host = (self.headers.get("Host") or "").strip().lower()
        name = urllib.parse.urlsplit("//" + host).hostname or ""
        try:
            ipaddress.ip_address(name)
        except ValueError:
            allowed = {"localhost", *(str(h).lower() for h in config.get("allowed_hosts") or [])}
            if name not in allowed:
                return True
        origin = (self.headers.get("Origin") or "").strip().lower()
        return bool(origin) and urllib.parse.urlsplit(origin).netloc != host

    def _allowed(self, path: str) -> bool:
        """Пускать ли запрос дальше. Статика открыта — экран входа рисует тот
        же интерфейс; закрыты данные и действия (/api/*), кроме самого входа.
        Чужая страница (_foreign) не получает /api/* вовсе, даже вход."""
        if hasattr(self.server, "phone_parent") and not self.server.phone_parent.phone_accepts(self.server):
            self.close_connection = True
            self._json({"error": "доступ с телефона выключен"}, 403)
            return False
        if path.startswith("/api") and self._foreign():
            self._drain_body()
            self._json({"error": "запрос с чужой страницы отклонён"}, 403)
            return False
        if not path.startswith("/api") or path.startswith("/api/auth"):
            return True
        if not self._auth_required() or self._auth_ok():
            return True
        self._drain_body()
        self._json({"error": "нужен пароль", "auth": True}, 401)
        return False

    def _api_auth_get(self):
        """GET /api/auth — нужен ли пароль и вошли ли уже. Сервер, который
        пароля не спрашивает (окно программы), отвечает, что вход уже есть."""
        required = self._auth_required()
        self._json({"required": required, "ok": not required or self._auth_ok()})

    def _api_auth_login(self):
        """POST /api/auth — вход по паролю: в ответе кука на год."""
        from modules import auth
        if not self._auth_required():
            self._json({"ok": True, "required": False})
            return
        left = auth.blocked_for(self._client_ip())
        if left:
            self._json({"error": "слишком много попыток — подождите %d мин"
                                 % max(1, round(left / 60))}, 429)
            return
        body, err = self._read_json()
        if err:
            self._json({"error": err}, 400)
            return
        password = (body or {}).get("password") if isinstance(body, dict) else None
        if not auth.check_password(password):
            auth.note_fail(self._client_ip())
            self._json({"error": "неверный пароль"}, 401)
            return
        auth.note_ok(self._client_ip())
        print("[auth] вход выполнен с %s" % self._client_ip())
        self._json({"ok": True},
                   headers=[("Set-Cookie", auth.set_cookie_header(self._secure_link()))])

    def _api_auth_logout(self):
        """POST /api/auth/logout — забыть куку на этом устройстве."""
        from modules import auth
        self._json({"ok": True},
                   headers=[("Set-Cookie", auth.clear_cookie_header(self._secure_link()))])

    def _read_json(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None, "некорректный Content-Length"
        if n <= 0:
            return None, "пустое тело запроса"
        if n > _MAX_BODY:
            return None, f"тело больше {_MAX_BODY} байт"
        raw = self.rfile.read(n)
        # тело прочитано: _drain_body из _json второй раз в сокет не полезет.
        # Отметка ставится ПОСЛЕ чтения, а не до: на ранних отказах выше (кривой
        # Content-Length, пустое или слишком большое тело) читать всё равно
        # придётся, и это сделает _drain_body
        self._body_done = True
        try:
            return json.loads(raw.decode("utf-8")), None
        except (ValueError, UnicodeDecodeError):
            return None, "тело не является корректным JSON"

    def log_message(self, fmt, *args):
        # напрямую в консоль, мимо журнала (modules/eventlog): опрос статуса
        # и журнала идёт раз в несколько секунд и забил бы ленту собой
        stream = sys.__stderr__ or sys.stderr
        if stream is None:
            return
        try:
            stream.write("%s - %s\n" % (self.address_string(), fmt % args))
        except (OSError, ValueError):
            # В GUI-сборке stderr может отсутствовать или быть закрыт.
            # send_response() вызывает log_message() ДО записи HTTP-статуса,
            # поэтому ошибка вывода лога не должна рвать само соединение.
            pass

    # --- маршрутизация ---

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if not self._allowed(path):
            return
        if path == "/api/auth":
            self._api_auth_get()
        elif path == "/api/config":
            self._json({"config": config.masked(), "file": config.CONFIG_FILE.name})
        elif path == "/api/proxies":
            self._json(self._proxies_payload())
        elif path == "/api/logs":
            self._api_logs()
        elif path == "/api/stream":
            self._api_stream()
        elif path == "/api/status":
            self._api_status()
        elif path == "/api/batch/status":
            from modules import batch_publish
            self._json(batch_publish.get_status())
        elif path == "/api/campaign/status":
            from modules import campaign
            self._json(campaign.get_status())
        elif path == "/api/campaign/form":
            self._json(self._campaign_form())
        elif path == "/api/accounts":
            from modules import accounts
            self._json({"accounts": accounts.list_accounts(),
                        "default_account": config.get("default_account"),
                        "banned": accounts.list_banned()})
        elif path == "/api/accounts/secrets":
            self._api_accounts_secrets()
        elif path == "/api/avatars":
            from modules import avatars
            self._json({"avatars": avatars.all_data()})
        elif path == "/api/studio/counters":
            self._json({"counters": _studio_counters()})
        elif path == "/api/anon":
            self._json({"via_server": True})  # анонимную личность держит сервер
        elif path == "/api/settings":
            self._api_settings_get()
        elif path == "/api/server/check":
            # доступен ли наш сервер по текущему адресу — для статуса в «Настройках»
            from modules import remote
            self._json(remote.ping())
        elif path == "/api/license":
            from modules import remote
            self._json(remote.status())
        elif path == "/api/license/avatar":
            from modules import remote
            try:
                data, ctype = remote.owner_avatar()
                self._bytes(data, ctype, "private, max-age=3600")
            except remote.RemoteError:
                self._json({"error": "аватар не найден"}, 404)
        elif path == "/api/license/history":
            self._api_license_history()
        elif path == "/api/changelog":
            from modules import changelog
            self._json(changelog.load())
        elif path == "/api/uniq":
            self._json(self._uniq_payload())
        elif path == "/api/media":
            from modules import photo_source
            self._json(photo_source.library())
        elif path in ("/api/media/files", "/api/media/thumb"):
            self._api_media_read(path.rsplit("/", 1)[-1])
        elif path == "/api/profiles/refresh":
            from modules import profiles
            self._json(profiles.status())
        elif path == "/api/accounts/purge":
            from modules import purge
            self._json(purge.status())
        elif path == "/api/profiles":
            from modules import profiles
            self._json({"profiles": profiles.list_all()})
        elif path.startswith("/api/profiles/"):
            self._api_profile_one(path)
        elif path == "/api/posts":
            from modules import profiles
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            username = (q.get("username") or [""])[0].lstrip("@")
            if not username:
                self._json({"error": "нужен username"}, 400)
            else:
                self._json({"username": username, "posts": profiles.posts_of(username)})
        elif path == "/api" or path.startswith("/api/"):
            self._json({"error": f"нет такого API-метода: {path}"}, 404)
        else:
            self._serve_static(path)

    def do_PUT(self):
        path = urllib.parse.urlparse(self.path).path
        if not self._allowed(path):
            return
        if path not in _PUT_ROUTES:
            self._json({"error": "PUT поддерживается только на "
                                 + ", ".join(_PUT_ROUTES)}, 404)
            return
        if path == "/api/proxies":
            self._api_proxies_put()
            return
        if path == "/api/settings":
            self._api_settings_put()
            return
        if path == "/api/license":
            self._api_license_put()
            return
        if path == "/api/uniq":
            self._api_uniq_put()
            return
        if path == "/api/campaign/form":
            self._api_campaign_form_put()
            return
        # остаётся /api/config — низкоуровневая запись в config.json
        body, err = self._read_json()
        if err:
            self._json({"error": err}, 400)
            return
        if not isinstance(body, dict):
            self._json({"error": "ожидается JSON-объект"}, 400)
            return
        try:
            cfg = config.update(body)
            self._json({"config": config.masked(cfg), "file": config.CONFIG_FILE.name})
        except OSError as exc:
            self._json({"error": f"не удалось записать config.json: {exc}"}, 500)

    def _api_logs(self):
        """GET /api/logs?after=<seq>&limit=<n>&debug=1 — журнал для вкладки «Логи».

        after — номер последней записи, которая уже есть у клиента: отдаём
        только то, что появилось позже. debug=1 — вместе с подробностями
        (stdout модулей), иначе только события. Записи без секретов
        (пароли и токены модули и так не печатают).

        В первой выдаче за запуск в ответе есть и записи прошлого запуска —
        eventlog поднимает хвост logs/events.log: они помечены полем past и
        идут раньше свежих, чтобы после перезапуска вкладка не показывала
        пустоту."""
        from modules import eventlog
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

        def _int(name, default):
            try:
                return int((query.get(name) or [default])[0])
            except (TypeError, ValueError):
                return default

        after = max(0, _int("after", 0))
        limit = min(500, max(1, _int("limit", 300)))
        self._json(eventlog.since(after=after, limit=limit,
                                  debug=_int("debug", 0) == 1))

    def _api_stream(self):
        """GET /api/stream?after=<seq>&debug=1&boot=<id> — живой поток UI
        (Server-Sent Events): журнал и прогресс публикации.

        Ответ не заканчивается: запись уходит клиенту в момент появления.
        Опрос раз в 4 с опаздывал, а пока «Войти во все» держала соединения
        браузера долгими входами (браузер даёт серверу не больше шести), опросы
        копились в очереди и потом приносили одни и те же записи по нескольку
        раз. У потока своё соединение на всё время жизни страницы.

        Первое сообщение — event: hello с номером запуска (eventlog.BOOT):
        клиент со страницы, открытой при прошлом процессе, по нему забывает
        старые номера записей. Следом — event: campaign, снимок как у GET
        /api/campaign/status; он же приходит на каждое изменение, но не чаще
        раза в CAMPAIGN_EVERY секунд. И event: profiles — ход обновления
        профилей (как GET /api/profiles/refresh) плюс свежие профили и
        аватарки аккаунтов, поменявшихся с прошлой отправки
        (profiles.changes): строка аккаунта обновляется в момент записи в
        базу, а не после всего прогона. И event: proxies — отметки проверки
        прокси (как health у GET /api/proxies): начали проверять, признали
        мёртвым, ожил. Записи журнала — сообщением без имени,
        пачкой JSON-массивом, id — номер последней; после обрыва браузер
        переподключается сам и шлёт его в Last-Event-ID. В первой пачке за
        запуск есть и записи прошлого запуска, поднятые из хвоста файла, — они
        помечены полем past и идут раньше свежих (как GET /api/logs). В тишине
        раз в 15 с уходит пинг-комментарий — на нём и выясняется, что вкладку
        закрыли."""
        from modules import campaign, eventlog, profiles
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

        def _int(value, default):
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        debug = _int((query.get("debug") or ["0"])[0], 0) == 1
        after = max(0, _int((query.get("after") or ["0"])[0], 0))
        after = max(0, _int(self.headers.get("Last-Event-ID"), after))
        boot = (query.get("boot") or [""])[0]
        if (boot and boot != eventlog.BOOT) or after > eventlog.last_seq():
            after = 0  # номера от прошлого запуска сервера — отдаём всё заново

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        def send_campaign():
            data = json.dumps(campaign.get_status(), ensure_ascii=False)
            self.wfile.write(("event: campaign\ndata: %s\n\n" % data).encode("utf-8"))

        # номер последнего отправленного изменения профилей: с новой страницы
        # или после обрыва — только ход обновления, строки она берёт списком
        profiles_seq = profiles.status()["seq"]

        def send_profiles():
            nonlocal profiles_seq
            chunk = profiles.changes(profiles_seq)
            profiles_seq = chunk["seq"]
            data = json.dumps(chunk, ensure_ascii=False)
            self.wfile.write(("event: profiles\ndata: %s\n\n" % data).encode("utf-8"))

        def send_proxies():
            data = json.dumps({"health": self._proxies_payload()["health"]},
                              ensure_ascii=False)
            self.wfile.write(("event: proxies\ndata: %s\n\n" % data).encode("utf-8"))

        try:
            self.wfile.write(("retry: 1000\nevent: hello\ndata: %s\n\n"
                              % eventlog.BOOT).encode("utf-8"))
            # счётчики берём ДО снимка: изменение между ними разбудит цикл
            # ниже, и клиент получит снимок ещё раз, а не потеряет его
            seen = eventlog.pulses()
            send_campaign()
            send_profiles()
            self.wfile.flush()
            campaign_at = profiles_at = time.monotonic()
            limit = 500  # первая пачка — хвост буфера, дальше всё новое целиком
            while True:
                if hasattr(self.server, "phone_parent") and not self.server.phone_parent.phone_accepts(self.server):
                    break
                chunk = eventlog.wait_since(after, debug, timeout=15, limit=limit,
                                            pulses=seen)
                limit = 0
                sent = False
                items = chunk["items"]
                if items:
                    after = items[-1]["seq"]
                    data = json.dumps(items, ensure_ascii=False)
                    self.wfile.write(("id: %d\ndata: %s\n\n" % (after, data)).encode("utf-8"))
                    sent = True
                now = chunk["pulses"]
                camp = now.get("campaign") != seen.get("campaign")
                prof = now.get("profiles") != seen.get("profiles")
                prox = now.get("proxies") != seen.get("proxies")
                if camp or prof or prox:
                    # воркеры двигают прогресс по нескольку раз в секунду —
                    # копим и шлём последний снимок, не чаще CAMPAIGN_EVERY;
                    # профили — пачкой всех, кто успел поменяться за PROFILES_EVERY;
                    # отметки прокси при проверке списка тоже летят пачкой
                    pause = 0.0
                    if camp or prox:
                        pause = self.CAMPAIGN_EVERY - (time.monotonic() - campaign_at)
                    if prof:
                        pause = max(pause, self.PROFILES_EVERY - (time.monotonic() - profiles_at))
                    if pause > 0:
                        time.sleep(pause)
                    now = eventlog.pulses()
                    if camp or now.get("campaign") != seen.get("campaign"):
                        send_campaign()
                        campaign_at = time.monotonic()
                    if prof or now.get("profiles") != seen.get("profiles"):
                        send_profiles()
                        profiles_at = time.monotonic()
                    if prox or now.get("proxies") != seen.get("proxies"):
                        send_proxies()
                        campaign_at = time.monotonic()
                    sent = True
                seen = now
                if not sent:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except OSError:
            pass  # вкладку закрыли или перезагрузили — поток больше некому слать

    def _settings_payload(self, cfg=None) -> dict:
        """Состояние вкладки «Настройки».

        bound — постоянный адрес окна; phone — отдельный вход из сети,
        включаемый без перезапуска."""
        from modules import auth, client_device, proxy_pool, remote
        cfg = cfg if cfg is not None else config.load()
        host, port = self.server.server_address[:2]
        phone_status = (self.server.phone_status() if hasattr(self.server, "phone_status")
                        else {"active": str(host) not in ("127.0.0.1", "::1"),
                              "supported": False, "links": phone_links(int(port))})
        return {"server": {"url": remote.base(), "default": remote.API_BASE,
                           "custom": bool(cfg.get("server_url"))},
                "browser_profile": cfg.get("browser_profile", "firefox155"),
                "browser_profile_active": client_device.browser_profile(),
                "browser_profiles": list(client_device.BROWSER_PROFILES),
                "threads": config.clamp_threads(cfg.get("threads")),
                "threads_max": config.THREADS_MAX,
                "proxy_on_death": proxy_pool.on_death(),
                "server_wait_min": config.clamp_server_wait(cfg.get("server_wait_min")),
                "server_wait_max": config.SERVER_WAIT_MAX,
                "port": cfg.get("port"),
                "host": cfg.get("host"),
                "bound": {"host": str(host), "port": int(port)},
                "phone": {"on": bool(cfg.get("phone_access")), **phone_status},
                "password": {"available": True,
                             "set": auth.enabled(),
                             "min_len": auth.MIN_LEN,
                             "required": self._auth_required() if hasattr(self, "_auth_required") else False}}

    def _api_license_put(self):
        """Ключ к нашему серверу: проверить у сервера и сохранить."""
        from modules import remote
        body, err = self._read_json()
        if err or not isinstance(body, dict):
            self._json({"error": err or "ожидается JSON-объект"}, 400)
            return
        try:
            self._json(remote.set_key(str(body.get("key") or "")))
        except remote.RemoteError as exc:
            self._json({"error": str(exc)}, 400)

    def _api_license_history(self):
        """Списания по ключу — постранично, курсором сервера."""
        from modules import remote
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        try:
            self._json(remote.history(int((q.get("limit") or ["50"])[0]),
                                      (q.get("cursor") or [None])[0]))
        except (remote.RemoteError, ValueError) as exc:
            self._json({"error": str(exc)}, 502)

    def _api_settings_get(self):
        """GET /api/settings — общие настройки программы для одноимённой вкладки."""
        self._json(self._settings_payload())

    def _api_settings_put(self):
        """PUT /api/settings — общие настройки: threads, proxy_on_death, port, host.

        Белый список: сюда ходит морда, и она не должна иметь возможности
        записать в config.json произвольный ключ (в отличие от низкоуровневого
        PUT /api/config, который принимает что дали). Пустое тело — не ошибка:
        UI шлёт только изменённое поле."""
        body, err = self._read_json()
        if err:
            self._json({"error": err}, 400)
            return
        if not isinstance(body, dict):
            self._json({"error": "ожидается JSON-объект"}, 400)
            return
        if "password" in body and "phone_access" in body:
            self._json({"error": "измените пароль и доступ с телефона отдельно"}, 400)
            return
        if "browser_profile" in body:
            from modules import client_device
            if body["browser_profile"] not in client_device.BROWSER_PROFILES:
                self._json({"error": "неподдерживаемый профиль браузера"}, 400)
                return
        if "server" in body:
            # свой адрес нашего сервера — пишем как ввели; отвечает ли он,
            # «Настройки» смотрят отдельно (GET /api/server/check)
            from modules import remote
            try:
                url = remote.set_server(str(body.get("server") or ""))
            except remote.RemoteError as exc:
                self._json({"error": str(exc)}, 400)
                return
            print(f"[settings] сервер: {url}")
        patch = {}
        if "browser_profile" in body:
            patch["browser_profile"] = body["browser_profile"]
        if "phone_access" in body:
            from modules import auth
            if not isinstance(body["phone_access"], bool):
                self._json({"error": "доступ с телефона — включён или выключен"}, 400)
                return
            on = body["phone_access"]
            if on and not auth.enabled() and not body.get("password"):
                self._json({"error": "сначала задайте пароль: с телефона "
                                     "пускаем только по нему"}, 400)
                return
            patch["phone_access"] = on
        if "threads" in body:
            # зажимаем, а не отказываем: ползунок в морде и так не даст лишнего,
            # а ручной запрос с 100 честнее выполнить по потолку, чем уронить
            patch["threads"] = config.clamp_threads(body.get("threads"))
        if "server_wait_min" in body:
            patch["server_wait_min"] = config.clamp_server_wait(body.get("server_wait_min"))
        if "proxy_on_death" in body:
            from modules import proxy_pool
            if body.get("proxy_on_death") not in proxy_pool.ON_DEATH:
                self._json({"error": "proxy_on_death — одно из: "
                                     + ", ".join(proxy_pool.ON_DEATH)}, 400)
                return
            patch[proxy_pool.ON_DEATH_KEY] = body["proxy_on_death"]
        if "port" in body:
            try:
                port = int(str(body.get("port")).strip())
            except (TypeError, ValueError):
                port = 0
            if not 1 <= port <= 65535:
                self._json({"error": "порт — целое число от 1 до 65535"}, 400)
                return
            patch["port"] = port
        if "host" in body:
            host = str(body.get("host") or "").strip()
            if not host or len(host) > 255 or any(c.isspace() for c in host):
                self._json({"error": "адрес — непустая строка без пробелов "
                                     "(0.0.0.0 — слушать на всех интерфейсах)"}, 400)
                return
            patch["host"] = host
        # пароль на интерфейс: хэш пишет modules/auth.py, в config.json
        # самого пароля нет. Смена пароля разлогинивает все устройства —
        # тому, кто менял, в ответе уходит новая кука
        headers = []
        if body.get("password") == "":
            # пустой пароль — снять. С телефона без пароля не пускаем вовсе,
            # поэтому при включённом доступе снимать нельзя
            from modules import auth
            phone_active = (self.server.phone_status()["active"]
                            if hasattr(self.server, "phone_status") else False)
            if config.get("phone_access") or phone_active:
                self._json({"error": "сначала выключите «С телефона»"}, 400)
                return
            try:
                auth.clear_password()
            except OSError as exc:
                self._json({"error": f"не удалось записать config.json: {exc}"}, 500)
                return
            print("[settings] пароль на интерфейс снят")
        elif "password" in body:
            from modules import auth
            try:
                auth.set_password(body.get("password"))
            except ValueError as exc:
                self._json({"error": str(exc)}, 400)
                return
            except OSError as exc:
                self._json({"error": f"не удалось записать config.json: {exc}"}, 500)
                return
            headers.append(("Set-Cookie", auth.set_cookie_header(self._secure_link())))
            print("[settings] пароль на интерфейс изменён")
        if not patch:
            self._json(self._settings_payload(), headers=headers)
            return
        phone_before = None
        if "phone_access" in patch:
            if not hasattr(self.server, "set_phone_access"):
                self._json({"error": "этот запуск не поддерживает переключение доступа с телефона"}, 409)
                return
            phone_before = self.server.phone_status()["active"]
            try:
                self.server.set_phone_access(patch["phone_access"])
            except OSError:
                self._json({"error": "не удалось открыть доступ в локальной сети"}, 409)
                return
        try:
            cfg = config.update(patch)
        except OSError as exc:
            if phone_before is not None:
                self.server.set_phone_access(phone_before)
            self._json({"error": f"не удалось записать config.json: {exc}"}, 500)
            return
        if "threads" in patch:
            print(f"[settings] потоков: {patch['threads']}")
        if "proxy_on_death" in patch:
            print(f"[settings] прокси умер: {patch['proxy_on_death']}")
        if "port" in patch or "host" in patch:
            print("[settings] адрес сервера сменится при следующем запуске")
        self._json(self._settings_payload(cfg), headers=headers)

    def _uniq_payload(self, state=None) -> dict:
        from modules import uniq
        state = state if state is not None else uniq.load()
        return dict(state, limits={
            "rotate": [-uniq.ROTATE_LIMIT, uniq.ROTATE_LIMIT],
            "compress": [1, uniq.QUALITY_LIMIT],
            "brightness": [-100, 100],
            "contrast": [-100, 100],
            "saturation": [-100, 100],
            "gamma": [-10, 10],
            "hue": [-180, 180],
            "scale": [0, uniq.SCALE_LIMIT],
        })

    def _api_uniq_put(self):
        """PUT /api/uniq — настройки уникализатора. Мусор не отвергаем, а
        зажимаем в пределы: ответ показывает, что реально записано."""
        body, err = self._read_json()
        if err:
            self._json({"error": err}, 400)
            return
        if not isinstance(body, dict):
            self._json({"error": "ожидается JSON-объект"}, 400)
            return
        from modules import uniq
        try:
            state = uniq.update(body)
        except OSError as exc:
            self._json({"error": f"не удалось записать config.json: {exc}"}, 500)
            return
        self._json(self._uniq_payload(state))

    def _api_uniq_preview(self):
        """POST /api/uniq/preview — как будет выглядеть уникализация.

        Настройки приходят из морды, а не читаются из конфига: ползунок только
        что сдвинули, и его сохранение может ещё быть в полёте."""
        body, err = self._read_json()
        if err:
            self._json({"error": err}, 400)
            return
        folders = body.get("folders") if isinstance(body, dict) else None
        if (not isinstance(folders, list) or not folders
                or not all(isinstance(f, str) and f.strip() for f in folders)):
            self._json({"error": "folders: непустой список путей к папкам"}, 400)
            return
        from modules import uniq
        settings = body.get("settings")
        state = uniq.normalize(settings) if isinstance(settings, dict) else uniq.load()
        items = []
        for folder in folders:
            try:
                items.append(uniq.preview(folder.strip(), state))
            except FileNotFoundError as exc:
                items.append({"error": str(exc)})
            except OSError as exc:
                items.append({"error": f"не удалось открыть фото: {exc}"})
        self._json({"items": items})

    # --- папки-слоты: сколько в них фото и загрузка новых ---

    def _api_slots_info(self):
        """POST /api/slots — по папке-слоту: есть ли она и сколько в ней фото и видео.

        Путь может быть и относительным — считается от папки, из которой
        запущена программа (так же, как при запуске публикации)."""
        body, err = self._read_json()
        if err:
            self._json({"error": err}, 400)
            return
        folders = body.get("folders") if isinstance(body, dict) else None
        if not isinstance(folders, list) or not all(isinstance(f, str) for f in folders):
            self._json({"error": "folders: список путей к папкам (строки)"}, 400)
            return
        from modules import photo_source
        items = []
        for folder in folders:
            path = Path(folder.strip()) if folder.strip() else None
            exists = bool(path and path.is_dir())
            items.append({
                "path": folder,
                "exists": exists,
                "photos": len(photo_source.list_slot_photos(path)) if exists else 0,
                "videos": (len(photo_source.list_slot_photos(path, "video"))
                           if exists else 0),
            })
        self._json({"items": items})

    def _api_media_read(self, action: str):
        """GET /api/media/files?name= — файлы папки программы;
        GET /api/media/thumb?name=&file= — превью фото (JPEG). Превью
        кэшируется браузером: интерфейс добавляет к адресу время правки файла."""
        from modules import photo_source
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        name = (query.get("name") or [""])[0]
        try:
            if action == "files":
                self._json({"files": photo_source.library_files(name)})
                return
            data = photo_source.library_thumb(name, (query.get("file") or [""])[0])
        except ValueError as exc:
            self._json({"error": str(exc)}, 404)
            return
        except OSError as exc:
            self._json({"error": f"файл не читается: {exc}"}, 500)
            return
        self._bytes(data, "image/jpeg", "private, max-age=86400")

    def _api_media(self, action: str):
        """POST /api/media[/clear|/delete] — завести, очистить, удалить папку
        программы. Пока идёт публикация, чистить и удалять нельзя: она берёт
        файлы прямо оттуда."""
        from modules import photo_source
        body, err = self._read_json()
        if err or not isinstance(body, dict):
            self._json({"error": err or "ожидается JSON-объект"}, 400)
            return
        name = body.get("name") if isinstance(body.get("name"), str) else ""
        try:
            if action == "media":
                self._json(photo_source.library_create(
                    name, body.get("default") if isinstance(body.get("default"), str) else ""))
                return
            if self._campaign_running():
                self._json({"error": "пока идёт публикация, папки не трогаем"}, 409)
                return
            if action == "clear":
                self._json({"ok": True, "removed": photo_source.library_clear(name)})
            elif action == "remove-file":
                file = body.get("file") if isinstance(body.get("file"), str) else ""
                photo_source.library_remove_file(name, file)
                self._json({"ok": True})
            else:
                photo_source.library_remove(name)
                self._json({"ok": True})
        except ValueError as exc:
            self._json({"error": str(exc)}, 400)
        except OSError as exc:
            self._json({"error": f"не вышло: {exc}"}, 500)

    def _api_slots_upload(self):
        """POST /api/slots/upload?folder=<папка>&name=<файл> — положить фото
        или видео в папку. Тело — сам файл, без multipart: один файл на запрос.

        Нужно для работы по ссылке (сервер, телефон), где системного «Обзора»
        нет. Пишется под временным именем и переименовывается в конце —
        публикация, идущая прямо сейчас, не подхватит недокачанный файл.
        Существующее фото не затирается: к имени добавляется номер."""
        from modules import photo_source
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        folder = (query.get("folder") or [""])[0].strip()
        name = Path((query.get("name") or [""])[0].replace("\\", "/")).name
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1

        def refuse(text, status=400):
            self._drain_body()
            self._json({"error": text}, status)

        if not folder:
            refuse("нужна папка (folder)")
            return
        suffix_lc = Path(name).suffix.lower() if name else ""
        is_video = suffix_lc in photo_source.MEDIA_EXTS["video"]
        if not name or not (is_video or suffix_lc in photo_source.PHOTO_EXTS):
            refuse("%s: это не фото и не видео" % (name or "файл"))
            return
        if length <= 0:
            refuse("пустой файл")
            return
        limit = _MAX_VIDEO_UPLOAD if is_video else _MAX_UPLOAD
        if length > limit:
            self.close_connection = True
            self._json({"error": "файл больше %s" % (
                "%d ГБ" % (limit // 1024 ** 3) if is_video
                else "%d МБ" % (limit // 1024 ** 2))}, 400)
            return

        target = Path(folder)
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            refuse("не удалось создать папку: %s" % exc)
            return

        stem, suffix = Path(name).stem, Path(name).suffix
        final = target / name
        for n in range(2, 1000):
            if not final.exists():
                break
            final = target / ("%s (%d)%s" % (stem, n, suffix))
        part = final.with_name(final.name + ".part")
        try:
            left = length
            with open(part, "wb") as out:
                while left > 0:
                    chunk = self.rfile.read(min(1024 * 1024, left))
                    if not chunk:
                        break
                    out.write(chunk)
                    left -= len(chunk)
            if left > 0:
                raise OSError("файл передан не полностью")
            # Как _read_json: тело уже прочитано, _json не должен читать его снова.
            self._body_done = True
            part.replace(final)
        except OSError as exc:
            try:
                part.unlink()
            except OSError:
                pass
            self.close_connection = True
            self._json({"error": "не удалось сохранить файл: %s" % exc}, 500)
            return
        print("[slots] %s: добавлено %s %s" % (folder, "видео" if is_video else "фото",
                                               final.name))
        self._json({"ok": True, "name": final.name,
                    "photos": len(photo_source.list_slot_photos(target)),
                    "videos": len(photo_source.list_slot_photos(target, "video"))})

    def _proxies_payload(self, cfg=None) -> dict:
        """Состояние раздела «Прокси» для UI.

        proxies — строки для textarea: канонический адрес и, если задана,
        ссылка смены IP через пробел. Ссылки хранятся отдельной мапой
        (config.proxy_rotate_urls), здесь они приклеиваются обратно.
        health — отметки проверки (modules/proxy_pool) в порядке строк."""
        from modules import proxy_pool, proxies as proxies_mod
        cfg = cfg if cfg is not None else config.load()
        links = cfg.get("proxy_rotate_urls") or {}
        urls = cfg.get("proxies") or []
        lines = []
        rotating = 0
        for url in urls:
            link = links.get(url) or ""
            lines.append(f"{url} {link}".strip())
            rotating += 1 if link else 0
        return {"proxies": lines,
                "rotating": rotating,
                "enabled": proxies_mod.as_bool(cfg.get("proxy_enabled"), False),
                "health": proxy_pool.snapshot(urls),
                "errors": []}

    def _api_proxies_check(self):
        """POST /api/proxies/check — проверить весь список разом и дождаться.

        Проверяется список целиком, даже при выключенном тумблере: пользователь
        хочет знать, что вставил, до того как включит. Идёт параллельно, на
        мёртвом прокси — до пары десятков секунд, на живом — пара секунд."""
        from modules import proxy_pool
        urls = config.get("proxies") or []
        if not urls:
            self._json({"error": "список прокси пуст"}, 400)
            return
        proxy_pool.check_all(urls)
        self._json(self._proxies_payload())

    def _api_proxies_rotate(self):
        """POST /api/proxies/rotate — сменить IP одной строки списка сейчас.

        body: {"index": N} — номер строки в config.proxies. Адрес ключом не
        годится: у пачки прокси одного провайдера он одинаковый. Дёргает
        ссылку смены IP (modules/proxies.rotate_for) и ждёт смены — от пары
        секунд до пары десятков на медленном провайдере; идёт из своего
        HTTP-потока, проход не держит. Ссылки нет — 400: у прокси нечего
        дёргать (поэтому skipped в ответе всегда false — «менять было нечего»
        сюда не доезжает, отказ приходит раньше). Ответ — {ok, changed,
        skipped, ip_before, ip_after, reason} и свежее состояние раздела, как у
        GET /api/proxies. changed — адрес на самом деле сменился: при
        выключенной проверке IP (proxy_rotate_verify) его не с чем сравнить, и
        он false, а адресов в ответе нет — по одному ok этот случай не отличить
        от «не проверяли».

        Настройки смены берём из config — те же, что у кампании и входа
        (rotate_for), поэтому пауза между сменами та же, что показывает
        нарисованный морде rotate_in. Аренды строка НЕ берёт — нарочно:
        аренду держит дело (аккаунт, вход, чистка), а кнопка меняет IP строке
        списка, за которой сейчас может не быть никого. Вместо аренды вердикт
        строки обновляем сразу после смены IP: проверка, шедшая в этот миг,
        успела увидеть прокси на середине смены и оставляла его «мёртвым» на
        минуты."""
        from modules import eventlog, proxies as proxies_mod, proxy_pool
        body, err = self._read_json()
        if err:
            self._json({"error": err}, 400)
            return
        if not isinstance(body, dict):
            self._json({"error": "ожидается JSON-объект с полем index"}, 400)
            return
        index = body.get("index")
        if not isinstance(index, int) or isinstance(index, bool):
            self._json({"error": "нужен номер строки: {\"index\": N}"}, 400)
            return
        urls = config.get("proxies") or []
        if not 0 <= index < len(urls):
            self._json({"error": "в списке нет строки прокси с номером %d" % index},
                       400)
            return
        entry = proxies_mod.entry_for(urls[index])
        if entry is None or not entry.rotate_url:
            self._json({"error": "у этого прокси нет ссылки смены IP"}, 400)
            return
        res = proxies_mod.rotate_for(entry, log=eventlog.teller(source="proxy"))
        payload = self._proxies_payload()
        # changed/skipped отдаём как есть (proxies.rotate_for): по адресам морда
        # судит, сменился ли IP, а changed говорит это прямо — при выключенной
        # проверке IP (proxy_rotate_verify) адресов в ответе нет вовсе, и по
        # одному ok нельзя отличить «сменён» от «не проверяли»
        payload.update(ok=res["ok"], changed=res["changed"],
                       skipped=res["skipped"], ip_before=res["ip_before"],
                       ip_after=res["ip_after"], reason=res["reason"])
        self._json(payload)
        # смена IP обнуляет прежний вердикт строки, а проверка, начатая до
        # клика, могла застать прокси на середине смены: свежий вердикт берём
        # фоном — ответа он не держит, а в ленту прилетит сам (pulse)
        threading.Thread(target=proxy_pool.check, args=(urls[index],),
                         name="proxy-check-rotate", daemon=True).start()

    def _api_proxies_put(self):
        """PUT /api/proxies — заменить список прокси для ротации кампанией.

        body: {"text": "строка\\nстрока"} ЛИБО {"proxies": [...]}. Каждая
        строка проходит умный разбор (modules/proxies.py): формат любой
        (host:port:user:pass, user:pass@host:port, socks5://…), ссылка смены
        IP выцепляется из той же строки. В конфиг уходят канонические адреса,
        ссылки — в proxy_rotate_urls. Строки, которые разобрать не удалось,
        возвращаются в "errors" с номером и причиной — молча их не теряем.
        Вместе со списком можно прислать отметки строк — НОМЕРАМИ в этом же
        списке: "login" (какие годятся для входа), "publish" (какие годятся
        для публикации) и "off" (какие
        выключены). Номерами, а не строками, нарочно: адрес у пачки от одного
        провайдера одинаковый, строки различаются только учётками, и по адресу
        их не развести. Список и отметки едут одним запросом, поэтому
        разъехаться не могут; номер вне списка молча пропускается.
        Плюс необязательный флаг, который можно передать и без text/proxies:
        "enabled" (bool, тумблер «использовать прокси»). 409 пока идёт кампания
        (менять прокси во время прохода нельзя).
        """
        body, err = self._read_json()
        if err:
            self._json({"error": err}, 400)
            return
        if not isinstance(body, dict):
            self._json({"error": "ожидается JSON-объект с полем text или proxies"}, 400)
            return
        if self._campaign_running():
            self._json({"error": "нельзя менять список прокси, пока идёт "
                                 "публикация — сначала остановите её"}, 409)
            return
        from modules import proxies as proxies_mod
        entries = None
        errors = []
        if "text" in body:
            text = body.get("text")
            if not isinstance(text, str):
                self._json({"error": "text должен быть строкой"}, 400)
                return
            entries, errors = proxies_mod.parse_text(text)
        elif "proxies" in body:
            raw_list = body.get("proxies")
            if (not isinstance(raw_list, list)
                    or not all(isinstance(x, str) for x in raw_list)):
                self._json({"error": "proxies должен быть списком строк"}, 400)
                return
            entries, errors = proxies_mod.parse_list(raw_list)
        elif not ({"enabled", "login", "publish", "off"} & set(body)):
            self._json({"error": "нужно поле text (строка), proxies (список) "
                                 "или отметки login/publish/off"}, 400)
            return

        patch = {}
        if entries is not None:
            patch["proxies"] = [e.url for e in entries]
            patch["proxy_rotate_urls"] = {e.url: e.rotate_url
                                          for e in entries if e.rotate_url}
            # названа ли схема в строке человека: в самом адресе её потом не
            # отличить от подставленной (см. _restore_scheme_knowledge)
            patch[SCHEME_NAMED_KEY] = {e.safe: e.named for e in entries}

        # Список, относительно которого считаются НОМЕРА отметок: только что
        # присланный, а если прислали одни отметки — нынешний из настроек.
        # Отдельно отметки шлёт переключатель на строке: дёрнул «вход» — незачем
        # гонять весь список туда-обратно, номера и так про тот список, который
        # сейчас на экране.
        ref = ([e.url for e in entries] if entries is not None
               else [p for p in (config.get("proxies") or []) if isinstance(p, str)])

        def _marked(field, key):
            """Номера строк -> их адреса, в patch. Поля НЕТ в теле — отметку не
            трогаем вовсе: список прилетает при каждой правке строки, и «нет
            поля = пусто» молча снимало бы все отметки при любом сохранении.
            Кривой номер и чужой тип пропускаем молча: отметка необязательна и
            сохранение списка ронять не должна."""
            if field not in body:
                return
            nums = body.get(field)
            picked = []
            if isinstance(nums, list):
                for n in nums:
                    if isinstance(n, bool) or not isinstance(n, int):
                        continue
                    if 0 <= n < len(ref):
                        picked.append(ref[n])
            patch[key] = picked

        _marked("login", "proxies_login")
        _marked("publish", "proxies_publish")
        _marked("off", "proxies_off")
        if "enabled" in body:
            patch["proxy_enabled"] = proxies_mod.as_bool(body.get("enabled"), False)
        try:
            # ссылки ротации и отметку схем заменяем целиком: удалённая строка
            # прокси должна унести и своё, слияние оставило бы их висеть.
            # Отметки строк — только те, что реально прислали (см. _marked):
            # не прислали поле, значит отметку не трогаем.
            replace = ()
            if entries is not None:
                replace = ("proxy_rotate_urls", SCHEME_NAMED_KEY) + tuple(
                    k for k in ("proxies_login", "proxies_publish", "proxies_off") if k in patch)
            cfg = config.update(patch, replace=replace)
        except OSError as exc:
            self._json({"error": f"не удалось записать config.json: {exc}"}, 500)
            return
        if entries is not None:
            from modules import proxy_pool
            proxy_pool.prune(cfg.get("proxies") or [])
        payload = self._proxies_payload(cfg)
        payload["errors"] = errors
        self._json(payload)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if not self._allowed(path):
            return
        if path == "/api/auth":
            self._api_auth_login()
        elif path == "/api/auth/logout":
            self._api_auth_logout()
        elif path == "/api/slots":
            self._api_slots_info()
        elif path == "/api/slots/upload":
            self._api_slots_upload()
        elif path in ("/api/media", "/api/media/clear", "/api/media/delete",
                      "/api/media/remove-file"):
            self._api_media(path.rsplit("/", 1)[-1])
        elif path == "/api/login":
            self._api_login()
        elif path == "/api/publish":
            self._api_publish()
        elif path == "/api/batch/start":
            self._api_batch_start()
        elif path == "/api/batch/stop":
            from modules import batch_publish
            self._json(batch_publish.request_stop())
        elif path == "/api/proxies/check":
            self._api_proxies_check()
        elif path == "/api/proxies/rotate":
            self._api_proxies_rotate()
        elif path == "/api/campaign/start":
            self._api_campaign_start()
        elif path == "/api/campaign/stop":
            from modules import campaign
            self._json(campaign.request_stop())
        elif path == "/api/logs/clear":
            from modules import eventlog
            eventlog.clear()
            self._json({"ok": True})
        elif path == "/api/accounts":
            self._api_accounts_add()
        elif path == "/api/accounts/bulk":
            self._api_accounts_bulk()
        elif path == "/api/accounts/update":
            self._api_accounts_update()
        elif path == "/api/accounts/delete":
            self._api_accounts_delete()
        elif path == "/api/accounts/clear-session":
            self._api_accounts_clear_session()
        elif path == "/api/accounts/logout":
            self._api_accounts_logout()
        elif path == "/api/accounts/restore":
            self._api_accounts_restore()
        elif path == "/api/accounts/disable":
            self._api_accounts_disable()
        elif path == "/api/accounts/default":
            self._api_accounts_default()
        elif path == "/api/accounts/purge":
            self._api_accounts_purge()
        elif path == "/api/profiles/refresh":
            self._api_profiles_refresh()
        elif path == "/api/profiles/fetch":
            self._api_profiles_fetch()
        elif path == "/api/uniq/preview":
            self._api_uniq_preview()
        else:
            self._json({"error": f"нет такого API-метода: {path}"}, 404)

    # --- статика из ui/ ---

    def _serve_static(self, path: str):
        """Собранный интерфейс (web/ -> ui/). Файлы из assets/ сборщик называет
        по хэшу содержимого — их кэшируем навсегда; index.html — всегда
        перепроверять, иначе после обновления программы окно покажет старый
        интерфейс со ссылками на уже удалённые файлы."""
        if path == "/":
            path = "/index.html"
        rel = urllib.parse.unquote(path.lstrip("/"))
        full = (UI_DIR / rel).resolve()
        if not full.is_relative_to(UI_DIR.resolve()) or not full.is_file():
            if rel == "index.html":
                self._json({"error": "интерфейс не собран: cd web, "
                                     "npm ci, npm run build:app"}, 503)
            else:
                self._json({"error": "не найдено"}, 404)
            return
        ctype = _STATIC_TYPES.get(full.suffix.lower(), "application/octet-stream")
        cache = ("public, max-age=31536000, immutable" if rel.startswith("assets/")
                 else "no-cache")
        self._bytes(full.read_bytes(), ctype, cache)

    def _bytes(self, data: bytes, ctype: str, cache: str = "no-cache"):
        """Ответ 200 с телом как есть: статика интерфейса, превью фото."""
        self._drain_body()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(data)

    # --- API-методы ---

    def _api_status(self):
        """Живость сессий клиент узнаёт у сервера через /api/accounts; старый
        адрес отвечает, куда идти (его ещё зовёт консоль разработчика)."""
        self._json({"error": "для серверного режима используйте /api/accounts"}, 410)

    def _campaign_running(self) -> bool:
        """Идёт ли кампания (running/stopping) — блокирует ручной login,
        publish и изменение списка аккаунтов."""
        from modules import campaign
        return campaign.get_status().get("status") in ("running", "stopping")

    def _campaign_form(self) -> dict:
        """Последняя заполненная форма публикации из config.campaign_form
        (UI подставляет значения в поля при старте; обновляются при каждом
        запуске публикации).

        Числа потоков здесь нет: оно общее на всю программу и живёт на вкладке
        «Настройки» (GET /api/settings).

        Тексты и паузы отдаются только если они уже записаны в конфиге:
        нативное окно exe работает без localStorage (приватный профиль), и
        пустышкой из старого конфига нельзя затирать тексты, взятые мордой из
        localStorage браузера."""
        from modules import batch_publish, campaign as campaign_mod
        form = config.get("campaign_form") or {}
        creatives = form.get("creatives")
        if creatives not in batch_publish.CREATIVES:
            # форма, сохранённая до выбора режима, знала только галочку «разные креативы»
            creatives = "unique" if form.get("unique_creatives") else "copies"
        data = {
            "posts_per_account": form.get("posts_per_account", 6),
            "delete_before": campaign_mod.normalize_delete_before(
                form.get("delete_before")),
            "creatives": creatives,
            "keep_photos": bool(form.get("keep_photos")),
            "slots": [s for s in (form.get("slots") or []) if isinstance(s, str)],
            # фото или видео; у видео своя папка — переключение режима не
            # сбивает набранные фото-слоты
            "media": form.get("media") if form.get("media") in ("photo", "video") else "photo",
            "video_slots": [s for s in (form.get("video_slots") or [])
                            if isinstance(s, str)],
            # повтор кругами: bool + число «через сколько» (от/до) и единица
            "repeat": bool(form.get("repeat")),
            "repeat_unit": form.get("repeat_unit")
                if form.get("repeat_unit") in _REPEAT_UNITS else "hour",
        }
        for key in ("repeat_min", "repeat_max"):
            if key in form:
                try:
                    data[key] = max(0, int(form.get(key) or 0))
                except (TypeError, ValueError):
                    pass
        for key in ("caption", "title"):
            if key in form:
                data[key] = str(form.get(key) or "")
        for key in ("min_delay_ms", "max_delay_ms"):
            if key in form:
                try:
                    data[key] = max(0, int(form.get(key) or 0))
                except (TypeError, ValueError):
                    data[key] = 0
        return data

    def _api_campaign_form_put(self):
        """PUT /api/campaign/form — запомнить форму сразу по ходу правки, а не только при запуске.
        Неполные поля (пустое «Постов», недонабранный режим) не пишутся — остаётся прежнее."""
        body, err = self._read_json()
        if err:
            self._json({"error": err}, 400)
            return
        if not isinstance(body, dict):
            self._json({"error": "ожидается JSON-объект"}, 400)
            return
        from modules import batch_publish, campaign as campaign_mod
        patch = {}
        for key in ("slots", "video_slots"):
            slots = body.get(key)
            if isinstance(slots, list) and all(isinstance(s, str) for s in slots):
                patch[key] = [s.strip() for s in slots if s.strip()]
        if body.get("media") in ("photo", "video"):
            patch["media"] = body["media"]
        try:
            ppa = int(body.get("posts_per_account"))
            if ppa >= 1:
                patch["posts_per_account"] = ppa
        except (TypeError, ValueError):
            pass
        if "delete_before" in body:
            patch["delete_before"] = campaign_mod.normalize_delete_before(body["delete_before"])
        if body.get("creatives") in batch_publish.CREATIVES:
            patch["creatives"] = body["creatives"]
        if "keep_photos" in body:
            patch["keep_photos"] = bool(body["keep_photos"])
        if "repeat" in body:
            patch["repeat"] = bool(body["repeat"])
        if body.get("repeat_unit") in _REPEAT_UNITS:
            patch["repeat_unit"] = body["repeat_unit"]
        for key in ("repeat_min", "repeat_max"):
            if key in body:
                try:
                    patch[key] = max(0, int(body.get(key) or 0))
                except (TypeError, ValueError):
                    pass
        # тексты поста и пауза между постами — та же форма, те же правила
        for key in ("caption", "title"):
            if key in body:
                patch[key] = str(body.get(key) or "")
        for key in ("min_delay_ms", "max_delay_ms"):
            if key in body:
                try:
                    patch[key] = max(0, int(body.get(key) or 0))
                except (TypeError, ValueError):
                    pass
        if patch:
            try:
                config.update({"campaign_form": patch})
            except OSError as exc:
                self._json({"error": f"не удалось записать config.json: {exc}"}, 500)
                return
        self._json(self._campaign_form())

    def _api_login(self):
        body, err = self._read_json()
        if err:
            self._json({"error": err}, 400)
            return
        username = (body or {}).get("username")
        if not username or not isinstance(username, str):
            self._json({"error": "нужен username (строка)"}, 400)
            return
        if self._campaign_running():
            self._json({"error": "нельзя логиниться вручную, пока идёт публикация — "
                                 "сначала остановите её"}, 409)
            return
        try:
            from modules import signin as login_impl
            ok = login_impl.run(username, tee=False)  # stdout сервера, не захват
            if ok:
                try:
                    config.update({"default_account": username})
                except OSError:
                    pass  # не критично — просто следующий publish возьмёт старый default_account
                self._json({"ok": True, "username": username})
            else:
                reason = login_impl.last_reason()
                # аккаунт удалён/забанен у TikTok или приостановлен (вход дал
                # один из BANNED_CODES, см. modules/login.py) — отключаем его
                # сразу и здесь, как в кампании: он исчезает из списка и больше
                # нигде не участвует, пока пользователь не вернёт его вручную.
                # Так «Войти» и «Войти во все» чистят мёртвые аккаунты так же,
                # как проход публикации
                if login_impl.last_banned():
                    from modules import accounts
                    accounts.mark_banned(
                        username, reason,
                        keep_session=login_impl.last_ban_code() in login_impl.KEEP_SESSION_CODES)
                    if config.get("default_account") == username:
                        try:
                            config.update({"default_account": None})
                        except OSError:
                            pass
                    self._json({"ok": False, "username": username,
                                "banned": True, "reason": reason})
                    return
                # human-readable причина из ответа TikTok (description/error_code) —
                # без секретов, login.py гарантирует это в last_reason()
                self._json({"ok": False, "username": username, "reason": reason})
        except ValueError as exc:
            # load_account: «аккаунт не найден» / «дефолт не выбран» —
            # текст уже человеческий, без секретов
            self._json({"ok": False, "error": str(exc)}, 404)
        except Exception as exc:  # noqa: BLE001
            self._json({"ok": False,
                        "error": f"{type(exc).__name__}: {exc}"}, 500)

    # --- аккаунты (modules/accounts.py) ---

    def _api_accounts_add(self):
        """POST /api/accounts — добавить/обновить аккаунт (по одному).

        Фронт этим больше не пользуется (перешёл на /api/accounts/bulk), но
        маршрут рабочий. В теле НЕТ секретов в ответах/логах: password/totp_secret проходят
        только в accounts.ACCOUNTS_FILE и не возвращаются.
        """
        body, err = self._read_json()
        if err:
            self._json({"error": err}, 400)
            return
        if not isinstance(body, dict):
            self._json({"error": "ожидается JSON-объект с полями username, "
                                 "password, totp_secret"}, 400)
            return
        if self._campaign_running():
            self._json({"error": "нельзя менять аккаунты, пока идёт публикация"}, 409)
            return
        from modules import accounts
        try:
            entry = accounts.add_account(body)
        except ValueError as exc:
            self._json({"error": str(exc)}, 400)
            return
        except OSError as exc:
            self._json({"error": f"не удалось записать accounts.json: {exc}"}, 500)
            return
        self._json({"ok": True, "username": entry["username"]})

    def _api_accounts_bulk(self):
        """POST /api/accounts/bulk — массовое добавление строк login:pass:2fa.

        Отдаёт 200 с {"added": [username...], "updated": [{"username",
        "replaced": [поле, ...]}], "errors": [{"line", "reason"}]} даже когда
        часть строк битые. Ключа "updated" нет, когда перезаписей не было
        (accounts.add_accounts_bulk добавляет его только при них), и в "added"
        такие логины не попадают. В ответе НЕТ содержимого строк (в них
        пароль!): только номер строки, причина и название заменённых полей.
        Полностью пустой/невалидный text — ValueError -> 400.
        """
        body, err = self._read_json()
        if err:
            self._json({"error": err}, 400)
            return
        text = body.get("text") if isinstance(body, dict) else None
        if self._campaign_running():
            self._json({"error": "нельзя менять аккаунты, пока идёт публикация"}, 409)
            return
        from modules import accounts
        try:
            result = accounts.add_accounts_bulk(text if isinstance(text, str) else "")
        except ValueError as exc:
            self._json({"error": str(exc)}, 400)
            return
        except OSError as exc:
            self._json({"error": f"не удалось записать accounts.json: {exc}"}, 500)
            return
        # поля ошибки перечисляем поимённо: в "text" разобранной не вышло строки
        # лежит пароль, и он не должен уехать в морду
        errors = [{"line": e.get("line"), "reason": e.get("reason")}
                  for e in result.get("errors", [])]
        out = {"added": result.get("added", []), "errors": errors}
        if result.get("updated"):
            out["updated"] = result["updated"]
        self._json(out)

    def _api_accounts_secrets(self):
        """GET /api/accounts/secrets?username=<логин> — пароль и источник

        кода аккаунта для формы ручной правки (единственное место, где
        секреты уходят наружу — см. правила modules/accounts.py). Ответ:
        {"password", "totp_secret"?, "email"?, "email_password"?} — только
        поля, которые реально сохранены. 400 — нет username, 404 — такого
        аккаунта нет.
        """
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        username = (q.get("username") or [""])[0]
        if not username:
            self._json({"error": "нужен username"}, 400)
            return
        from modules import accounts
        try:
            self._json(accounts.secrets_of(username))
        except ValueError as exc:
            self._json({"error": str(exc)}, 404)

    def _api_accounts_update(self):
        """POST /api/accounts/update — ручная правка одного аккаунта: пароль

        сменился, логин определился неверно при вставке и т.п.

        body: {\"username\" — существующий логин, чей аккаунт правим,
        \"patch\": {username?, password?, totp_secret?, email?,
        email_password?}}. В patch присутствует только то, что
        человек поменял в форме: непустая строка — новое значение, пустая —
        снять поле (кроме username/password — их снять нельзя), поле вовсе
        отсутствует — не трогаем. Ответ — запись БЕЗ секретов (как элемент
        GET /api/accounts), 400 — теряется обязательное поле или новый
        username уже занят, 404 — аккаунта с таким username нет.
        """
        body, err = self._read_json()
        if err:
            self._json({"error": err}, 400)
            return
        if not isinstance(body, dict):
            self._json({"error": "ожидается JSON-объект с полями username, patch"}, 400)
            return
        username = body.get("username")
        patch = body.get("patch")
        if not username or not isinstance(username, str):
            self._json({"error": "нужен username (строка) — какой аккаунт правим"}, 400)
            return
        if not isinstance(patch, dict):
            self._json({"error": "нужен patch (JSON-объект с изменёнными полями)"}, 400)
            return
        if self._campaign_running():
            self._json({"error": "нельзя менять аккаунты, пока идёт публикация"}, 409)
            return
        from modules import accounts
        try:
            entry = accounts.update_account(username, patch)
        except ValueError as exc:
            msg = str(exc)
            self._json({"error": msg}, 404 if "не найден" in msg else 400)
            return
        except OSError as exc:
            self._json({"error": f"не удалось записать accounts.json: {exc}"}, 500)
            return
        self._json(entry)

    def _profiles_body(self):
        """Общее тело для fetch/refresh: (usernames|None, method, with_posts, err).
        Тело необязательно; usernames нет -> None (значит «все аккаунты»)."""
        body = {}
        if int(self.headers.get("Content-Length") or 0) > 0:
            body, err = self._read_json()
            if err:
                return None, None, True, err
            if not isinstance(body, dict):
                return None, None, True, "тело: JSON-объект"
        method = body.get("method")
        with_posts = body.get("posts", True)
        usernames = body.get("usernames")
        if usernames is None and body.get("username"):
            usernames = body["username"]
        return usernames, method, bool(with_posts), None

    def _profiles_targets(self, usernames):
        """usernames из тела или, если их нет, все username из accounts.json."""
        if usernames is not None:
            return usernames
        from modules import accounts
        return [a["username"] for a in accounts.list_accounts()]

    def _api_profiles_refresh(self):
        """POST /api/profiles/refresh — фоном обновить профили, посты и аватарки
        без входа, через прокси (modules/profiles.py).

        Тело необязательно: {"usernames": [...] (по умолчанию все аккаунты),
        "method": "detail"|"ssr", "posts": true}. Идёт обновление — имена
        добавляются в его очередь, а не отказ. 400 — неверный запрос,
        409 — нет прокси.
        """
        usernames, method, with_posts, err = self._profiles_body()
        if err:
            self._json({"error": err}, 400)
            return
        from modules import profiles
        try:
            self._json(profiles.start(self._profiles_targets(usernames), method, with_posts))
        except profiles.ProfileInputError as exc:
            self._json({"error": str(exc)}, 400)
        except profiles.ProfileError as exc:
            self._json({"error": str(exc)}, 409)

    def _api_profiles_fetch(self):
        """POST /api/profiles/fetch — забрать профили сейчас и вернуть их же
        (синхронно, до profiles.FETCH_NOW_MAX юзернеймов). Тело как у refresh.
        Ответ: {"profiles": [...], "failed": [{username, reason}]}."""
        usernames, method, with_posts, err = self._profiles_body()
        if err:
            self._json({"error": err}, 400)
            return
        from modules import profiles
        try:
            self._json(profiles.fetch_now(self._profiles_targets(usernames), method, with_posts))
        except profiles.ProfileInputError as exc:
            self._json({"error": str(exc)}, 400)
        except profiles.ProfileError as exc:
            self._json({"error": str(exc)}, 409)

    def _api_profile_one(self, path: str):
        """GET /api/profiles/<@имя> — один сохранённый профиль (404, если нет)."""
        from modules import profiles
        name = urllib.parse.unquote(path[len("/api/profiles/"):]).lstrip("@")
        prof = profiles.get(name) if name else None
        if prof:
            self._json(prof)
        else:
            self._json({"error": f"профиль {name} не забирали"}, 404)


    def _api_accounts_delete(self):
        """POST /api/accounts/delete — убрать аккаунт (+ его jar)."""
        body, err = self._read_json()
        if err:
            self._json({"error": err}, 400)
            return
        username = (body or {}).get("username")
        if not username or not isinstance(username, str):
            self._json({"error": "нужен username (строка)"}, 400)
            return
        if self._campaign_running():
            self._json({"error": "нельзя менять аккаунты, пока идёт публикация"}, 409)
            return
        from modules import accounts, remote
        try:
            removed = accounts.remove_account(username, new_device=_new_device(body))
        except remote.RemoteError as exc:
            self._json({"error": _DEVICE_NOT_KEPT % exc}, 502)
            return
        if not removed:
            self._json({"error": f"аккаунт {username} не найден"}, 404)
            return
        out = {"ok": True, "username": username}
        if config.get("default_account") == username:
            try:
                config.update({"default_account": None})
                out["default_reset"] = True
                out["note"] = "аккаунт был аккаунтом по умолчанию — выбор сброшен"
            except OSError:
                pass  # конфиг не записался — аккаунт удалён, дефолт устареет
        self._json(out)

    def _api_accounts_clear_session(self):
        """POST /api/accounts/clear-session — стереть сессию, не аккаунт.

        Запись в accounts.json, секреты и default_account остаются:
        после этого тот же аккаунт можно вновь авторизовать через /api/login.
        В TikTok ничего не отправляет: это только локальная очистка.
        Если jar уже нет, ответ всё равно успешный (had_session=false).
        """
        body, err = self._read_json()
        if err:
            self._json({"error": err}, 400)
            return
        if not isinstance(body, dict):
            self._json({"error": "ожидается JSON-объект с полем username"}, 400)
            return
        username = body.get("username")
        if not isinstance(username, str) or not username.strip():
            self._json({"error": "нужен username (непустая строка)"}, 400)
            return
        if self._campaign_running():
            self._json({"error": "нельзя разлогинивать аккаунт, пока идёт "
                                 "публикация — сначала остановите её"}, 409)
            return
        from modules import accounts, remote
        try:
            result = accounts.clear_session(username, new_device=_new_device(body))
        except ValueError as exc:
            self._json({"error": str(exc)}, 404)
            return
        except remote.RemoteError as exc:
            self._json({"error": _DEVICE_NOT_KEPT % exc}, 502)
            return
        except OSError as exc:
            self._json({"error": f"не удалось очистить сессию: {exc}"}, 500)
            return
        self._json({"ok": True, "username": result["username"],
                    "had_session": bool(result.get("files_removed"))})

    def _api_accounts_logout(self):
        """POST /api/accounts/logout — настоящий выход у TikTok, не только
        локально (в отличие от /api/accounts/clear-session).

        Гасит веб-сессию аккаунта на стороне TikTok (modules/login.remote_logout)
        через прокси из пула входа — без него запрос слишком заметен для WAF;
        remote_logout сам арендует прокси и при отсутствии живого возвращает
        структурную ошибку (ok=false), а не ходит мимо прокси. Статус ответа
        всегда 200 — исход смотрят по полю "confirmed"/"error", как у /api/login.

        Подтверждённый TikTok выход сразу чистит и локальный файл сессии:
        иначе программа продолжала бы считать мёртвую сессию рабочей —
        session_defects/has_session смотрят только на форму локальных cookies,
        а не на их силу у TikTok. Неподтверждённый выход локальный файл не
        трогает (may_clear_local=false) — мало ли что произошло на середине.
        """
        body, err = self._read_json()
        if err:
            self._json({"error": err}, 400)
            return
        if not isinstance(body, dict):
            self._json({"error": "ожидается JSON-объект с полем username"}, 400)
            return
        username = body.get("username")
        if not isinstance(username, str) or not username.strip():
            self._json({"error": "нужен username (непустая строка)"}, 400)
            return
        if self._campaign_running():
            self._json({"error": "нельзя разлогинивать аккаунт, пока идёт "
                                 "публикация — сначала остановите её"}, 409)
            return
        from modules import accounts, cloud, proxy_pool, remote
        try:
            held = proxy_pool.lease(task="login")
            try:
                out = cloud.logout(username, held.url)
            finally:
                held.release()
            result = {**out, "may_clear_local": out.get("confirmed")}
        except (proxy_pool.NoAliveProxy, remote.RemoteError) as exc:
            result = {"ok": False, "confirmed": False, "may_clear_local": False,
                      "error": str(exc)}
        had_session = False
        if result.get("may_clear_local"):
            try:
                cleared = accounts.clear_session(username, new_device=_new_device(body))
            except ValueError:
                pass  # аккаунта уже нет в списке — очищать нечего
            except remote.RemoteError as exc:
                # у TikTok вышли, а компьютер не сохранился — вход остаётся
                # на месте, чтобы его не потерять; повторят или сменят устройство
                result["error"] = _DEVICE_NOT_KEPT % exc
            else:
                had_session = bool(cleared.get("files_removed"))
        self._json({"ok": bool(result.get("confirmed")),
                    "username": username,
                    "confirmed": bool(result.get("confirmed")),
                    "had_session": had_session,
                    "error": result.get("error")})

    def _api_accounts_restore(self):
        """POST /api/accounts/restore — вернуть забаненный аккаунт из banned.json
        обратно в список (если бан оказался ошибкой)."""
        body, err = self._read_json()
        if err:
            self._json({"error": err}, 400)
            return
        username = (body or {}).get("username")
        if not username or not isinstance(username, str):
            self._json({"error": "нужен username (строка)"}, 400)
            return
        if self._campaign_running():
            self._json({"error": "нельзя менять аккаунты, пока идёт публикация"}, 409)
            return
        from modules import accounts
        if not accounts.restore_banned(username):
            self._json({"error": f"забаненного аккаунта {username} нет"}, 404)
            return
        self._json({"ok": True, "username": username})

    def _api_accounts_disable(self):
        """POST /api/accounts/disable — вручную отключить аккаунт(ы) (body:
        {"usernames": [...]}, одиночный {"username"} тоже принимается).

        Переносит каждый в banned.json с причиной "отключён вручную" и
        keep_session=True — «Вернуть» отдаст его обратно с живой сессией.
        Для случаев вроде «такого юзернейма нет», когда автоотключения нет
        намеренно, но аккаунт всё равно пора убрать из активных."""
        body, err = self._read_json()
        if err:
            self._json({"error": err}, 400)
            return
        body = body or {}
        usernames = body.get("usernames")
        if usernames is None:
            single = body.get("username")
            usernames = [single] if single else []
        if not isinstance(usernames, list) or not usernames or \
                not all(isinstance(u, str) and u for u in usernames):
            self._json({"error": "нужен usernames (список строк) или username (строка)"}, 400)
            return
        if self._campaign_running():
            self._json({"error": "нельзя менять аккаунты, пока идёт публикация"}, 409)
            return
        from modules import accounts
        disabled, missing = [], []
        for username in usernames:
            if accounts.mark_banned(username, reason="отключён вручную", keep_session=True):
                disabled.append(username)
            else:
                missing.append(username)
        self._json({"ok": True, "disabled": disabled, "missing": missing})

    def _api_accounts_purge(self):
        """POST /api/accounts/purge — снести посты аккаунта.

        body: {"username", "count"}; count — число или "all" (по умолчанию
        "all"). Работа идёт в фоне, ход виден в журнале: удаление всей ленты
        занимает по запросу на пост и на HTTP-ответе не удержать.
        409 — этот аккаунт уже чистится (статус — GET /api/accounts/purge).
        """
        body, err = self._read_json()
        if err:
            self._json({"error": err}, 400)
            return
        body = body or {}
        username = body.get("username")
        if not username or not isinstance(username, str):
            self._json({"error": "нужен username (строка)"}, 400)
            return
        if self._campaign_running():
            self._json({"error": "нельзя чистить аккаунт, пока идёт публикация"}, 409)
            return

        from modules import accounts, campaign as campaign_mod
        known = [a.get("username") for a in accounts.list_accounts()]
        if username not in known:
            self._json({"error": f"аккаунт {username} не найден"}, 404)
            return

        count = campaign_mod.resolve_delete_count(body.get("count", -1), 0)
        if not count:
            self._json({"error": "count: число больше нуля или -1 (всё)"}, 400)
            return

        from modules import purge
        _taken, busy = purge.claim([username])
        if busy:
            self._json({"error": f"{username} уже чистится"}, 409)
            return

        threading.Thread(target=purge.run_manual, args=(username, count),
                         daemon=True).start()
        self._json({"ok": True, "username": username, "count": count}, 202)

    def _api_accounts_default(self):
        """POST /api/accounts/default — выбрать аккаунт по умолчанию."""
        body, err = self._read_json()
        if err:
            self._json({"error": err}, 400)
            return
        username = (body or {}).get("username")
        if not username or not isinstance(username, str):
            self._json({"error": "нужен username (строка)"}, 400)
            return
        if self._campaign_running():
            self._json({"error": "нельзя менять аккаунты, пока идёт публикация"}, 409)
            return
        from modules import accounts
        if username not in [a["username"] for a in accounts.list_accounts()]:
            self._json({"error": f"аккаунт {username} не найден"}, 404)
            return
        try:
            config.update({"default_account": username})
        except OSError as exc:
            self._json({"error": f"не удалось записать config.json: {exc}"}, 500)
            return
        self._json({"ok": True, "username": username})

    def _api_publish(self):
        body, err = self._read_json()
        if err:
            self._json({"error": err}, 400)
            return
        body = body or {}
        # оба необязательные — реальные посты бывают вообще без подписи/заголовка
        caption = body.get("caption") or ""
        photos = body.get("photos")
        title = body.get("title") or ""
        if not isinstance(caption, str):
            self._json({"error": "caption должен быть строкой"}, 400)
            return
        if not isinstance(title, str):
            self._json({"error": "title должен быть строкой"}, 400)
            return
        # нельзя публиковать одиночный пост, пока идёт батч — batch_publish.py
        # добавляется параллельно другой задачей и может ещё не существовать
        try:
            from modules import batch_publish
            st = batch_publish.get_status()
            if st.get("status") in ("running", "stopping"):
                self._json({"error": "нельзя публиковать одиночный пост, пока "
                                     "выполняется батч — сначала остановите его"}, 409)
                return
        except ImportError:
            pass  # батч ещё не реализован — считаем, что он не идёт
        # нельзя публиковать одиночный пост, пока идёт кампания — она сама
        # переключает config.default_account и дёргает batch_publish
        from modules import campaign
        if campaign.get_status().get("status") in ("running", "stopping"):
            self._json({"error": "нельзя публиковать одиночный пост, пока "
                                 "выполняется публикация — сначала остановите её"}, 409)
            return
        if photos is None:
            photos = []
        if (not isinstance(photos, list) or not photos
                or not all(isinstance(p, str) and p for p in photos)):
            self._json({"error": "photos: непустой список путей — папка "
                                 "(возьмётся следующее фото из неё) или "
                                 "конкретный файл"}, 400)
            return
        from modules.photo_source import resolve_photo_path
        resolved = []
        for p in photos:
            try:
                resolved.append(resolve_photo_path(p))
            except FileNotFoundError as exc:
                self._json({"error": str(exc)}, 400)
                return
        from modules import proxy_pool
        try:
            held = proxy_pool.lease(task="publish")
        except proxy_pool.ProxySelectionError as exc:
            self._json({"error": str(exc)}, 409)
            return
        except proxy_pool.NoAliveProxy as exc:
            self._json({"error": str(exc)}, 503)
            return
        from modules import cloud, photo_source
        username = config.get("default_account")
        via = (username, held.url)
        try:
            photos_result = photo_source.prepare_post_photos(resolved, via=via)
        except photo_source.PhotoConsumeError as exc:
            held.release()
            # фото уже вернулись в папки — сообщаем только про сбойный файл
            self._json({
                "error": str(exc),
                "consumed": [],
                "failed_path": exc.failed_path,
            }, 500)
            return
        except Exception as exc:  # noqa: BLE001
            held.release()
            self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
            return
        try:
            # ВСЕГДА живая публикация: поле dry_run из тела игнорируется —
            # UI это единственный путь пользователя к реальной публикации.
            result = cloud.publish_photo_items(*via, photos_result, caption, title)
        except Exception as exc:  # noqa: BLE001
            photo_source.burn_photos(photos_result)
            self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
            return
        finally:
            held.release()
        # фото уже ушли на серверы TikTok — списываем их в любом случае,
        # вышел пост или нет (повторный залив засветившегося фото даёт тень)
        if result.get("ok"):
            photo_source.commit_photos(photos_result)
        else:
            photo_source.burn_photos(photos_result)
        self._json({
            "ok": result.get("ok"),
            "verdict": result.get("verdict"),
            "code": result.get("code"),
            "message": result.get("message"),
            "item_id": result.get("item_id"),
            "project_id": result.get("project_id"),
            "attempts": result.get("attempts"),
            "consumed": [item.get("path") for item in photos_result],
        })

    def _api_batch_start(self):
        body, err = self._read_json()
        if err:
            self._json({"error": err}, 400)
            return
        body = body or {}
        slots = body.get("slots")
        caption = body.get("caption") or ""
        title = body.get("title") or ""
        min_delay_ms = body.get("min_delay_ms", 0)
        max_delay_ms = body.get("max_delay_ms", 0)

        if not isinstance(caption, str) or not isinstance(title, str):
            self._json({"error": "caption/title должны быть строками"}, 400)
            return
        if (not isinstance(slots, list) or not slots
                or not all(isinstance(s, str) and s for s in slots)):
            self._json({"error": "slots: непустой список путей к папкам "
                                 "(строки)"}, 400)
            return
        for i, s in enumerate(slots):
            if not Path(s).is_dir():
                self._json({"error": f"слот №{i + 1}: не найдена папка {s}"}, 400)
                return
        resolved = [str(Path(s).resolve()) for s in slots]
        if len(set(resolved)) != len(resolved):
            self._json({"error": "два слота указывают на одну и ту же папку — "
                                 "слоты должны быть разными"}, 400)
            return
        try:
            min_delay_ms = int(min_delay_ms)
            max_delay_ms = int(max_delay_ms)
        except (TypeError, ValueError):
            self._json({"error": "min_delay_ms/max_delay_ms должны быть целыми"}, 400)
            return
        if min_delay_ms < 0 or max_delay_ms < 0 or min_delay_ms > max_delay_ms:
            self._json({"error": "нужно 0 <= min_delay_ms <= max_delay_ms"}, 400)
            return

        account = config.get("default_account")
        limit = int((config.load().get("flags") or {}).get("posts_per_account", 6))

        from modules import batch_publish, proxy_pool
        try:
            status = batch_publish.start_batch(
                slots, caption, title, min_delay_ms, max_delay_ms, account, limit)
        except batch_publish.BatchAlreadyRunningError:
            self._json({"error": "батч уже выполняется"}, 409)
            return
        except proxy_pool.ProxySelectionError as exc:
            self._json({"error": str(exc)}, 409)
            return
        except proxy_pool.NoAliveProxy as exc:
            self._json({"error": str(exc)}, 503)
            return
        self._json({"ok": True, "status": status}, 202)

    def _api_campaign_start(self):
        body, err = self._read_json()
        if err:
            self._json({"error": err}, 400)
            return
        body = body or {}
        # зеркально чистке постов (она не стартует при идущей кампании):
        # кампания не стартует при идущей чистке — иначе оба лезли бы на один
        # аккаунт и писали один jar сессии наперебой
        from modules import purge
        purging = purge.current()
        if purging:
            self._json({"error": "нельзя начать публикацию, пока идёт чистка "
                                 "постов (%d) — дождитесь её конца"
                                 % len(purging)}, 409)
            return
        slots = body.get("slots")
        caption = body.get("caption") or ""
        title = body.get("title") or ""
        min_delay_ms = body.get("min_delay_ms", 0)
        max_delay_ms = body.get("max_delay_ms", 0)
        posts_per_account = body.get("posts_per_account")
        media = body.get("media", "photo")
        if media not in ("photo", "video"):
            self._json({"error": "media: photo | video"}, 400)
            return

        if not isinstance(caption, str) or not isinstance(title, str):
            self._json({"error": "caption/title должны быть строками"}, 400)
            return
        if (not isinstance(slots, list) or not slots
                or not all(isinstance(s, str) and s for s in slots)):
            self._json({"error": "slots: непустой список путей к папкам "
                                 "(строки)"}, 400)
            return
        if media == "video" and len(slots) != 1:
            self._json({"error": "для видео нужна одна папка с роликами"}, 400)
            return
        for i, s in enumerate(slots):
            if not Path(s).is_dir():
                where = "папка с видео" if media == "video" else f"слот №{i + 1}"
                self._json({"error": f"{where}: не найдена папка {s}"}, 400)
                return
        resolved = [str(Path(s).resolve()) for s in slots]
        if len(set(resolved)) != len(resolved):
            self._json({"error": "два слота указывают на одну и ту же папку — "
                                 "слоты должны быть разными"}, 400)
            return
        try:
            min_delay_ms = int(min_delay_ms)
            max_delay_ms = int(max_delay_ms)
        except (TypeError, ValueError):
            self._json({"error": "min_delay_ms/max_delay_ms должны быть целыми"}, 400)
            return
        if min_delay_ms < 0 or max_delay_ms < 0 or min_delay_ms > max_delay_ms:
            self._json({"error": "нужно 0 <= min_delay_ms <= max_delay_ms"}, 400)
            return
        if posts_per_account is None or posts_per_account == "":
            posts_per_account = int(config.load()["flags"]["posts_per_account"])
        else:
            try:
                posts_per_account = int(posts_per_account)
            except (TypeError, ValueError):
                self._json({"error": "posts_per_account должен быть целым числом"}, 400)
                return
            if posts_per_account < 1:
                self._json({"error": "posts_per_account должен быть >= 1"}, 400)
                return

        # threads — сколько аккаунтов обрабатываются одновременно (1 = как
        # раньше, последовательно)
        # что снести с аккаунта перед заливом: ничего, столько же, сколько
        # публикуем ("same"), своё число или все посты ("all")
        from modules import campaign as campaign_mod
        delete_before = campaign_mod.normalize_delete_before(
            body.get("delete_before"))

        from modules import batch_publish
        creatives = body.get("creatives", "copies")
        if creatives not in batch_publish.CREATIVES:
            self._json({"error": "creatives: " + " | ".join(batch_publish.CREATIVES)}, 400)
            return
        keep_photos = bool(body.get("keep_photos"))

        # повтор кругами: закончив проход по всем аккаунтам, кампания ждёт
        # случайную паузу из [repeat_min, repeat_max] в единицах repeat_unit
        # и начинает круг заново — так до «Остановить». repeat_unit —
        # "min"|"hour"; выключено (по умолчанию) — один проход, как раньше.
        repeat = bool(body.get("repeat"))
        repeat_unit = body.get("repeat_unit", "hour")
        repeat_min_sec = repeat_max_sec = 0
        if repeat:
            if repeat_unit not in _REPEAT_UNITS:
                self._json({"error": "repeat_unit: " + " | ".join(_REPEAT_UNITS)}, 400)
                return
            repeat_min_sec = _repeat_seconds(body.get("repeat_min"), repeat_unit)
            repeat_max_sec = _repeat_seconds(body.get("repeat_max"), repeat_unit)
            if repeat_min_sec <= 0 or repeat_max_sec <= 0:
                self._json({"error": "повтор через: числа больше нуля"}, 400)
                return
            if repeat_min_sec > repeat_max_sec:
                self._json({"error": "повтор «от» не может быть больше «до»"}, 400)
                return

        # публикация по выбранным аккаунтам (кнопка в разделе «Аккаунты»):
        # список username или пусто — по всем, как раньше
        accounts = body.get("accounts")
        if accounts is not None and (
                not isinstance(accounts, list)
                or not all(isinstance(a, str) and a for a in accounts)):
            self._json({"error": "accounts: список имён аккаунтов (строки)"}, 400)
            return

        # сколько аккаунтов идут одновременно — общая настройка «потоки»
        # (вкладка «Настройки»), из формы публикации это поле убрано: одно
        # число на всю программу, иначе значения разъезжаются по разделам.
        # В теле запроса threads всё ещё принимается — для ручных вызовов API.
        threads = body.get("threads")
        if threads is not None:
            threads = config.clamp_threads(threads)

        # запоминаем форму публикации: следующий старт (даже в другом
        # браузере) подставит те же значения в поля
        try:
            form = {
                "posts_per_account": posts_per_account,
                "delete_before": delete_before,
                "creatives": creatives,
                "keep_photos": keep_photos,
                "media": media,
                "slots" if media == "photo" else "video_slots": resolved,
                "caption": caption,
                "title": title,
                "min_delay_ms": min_delay_ms,
                "max_delay_ms": max_delay_ms,
                "repeat": repeat,
                "repeat_unit": repeat_unit if repeat_unit in _REPEAT_UNITS else "hour",
            }
            # число «через сколько» кладём как есть, чтобы форма подставила его
            # обратно; хранится в единицах repeat_unit, не в секундах
            for key in ("repeat_min", "repeat_max"):
                try:
                    form[key] = max(0, int(body.get(key) or 0))
                except (TypeError, ValueError):
                    pass
            config.update({"campaign_form": form})
        except OSError:
            pass  # не критично — форма просто не запомнится

        from modules import campaign, proxy_pool
        try:
            # Пустая группа — ошибка до запуска фоновой кампании, чтобы UI
            # сразу сказал, что именно надо отметить, а не принял запуск 202.
            proxy_pool.configured("publish")
            status = campaign.start_campaign(
                slots, caption, title, min_delay_ms, max_delay_ms,
                posts_per_account, threads=threads,
                delete_before=delete_before,
                creatives=creatives, keep_photos=keep_photos,
                accounts=accounts, repeat=repeat,
                repeat_min_sec=repeat_min_sec, repeat_max_sec=repeat_max_sec,
                media=media)
        except campaign.CampaignAlreadyRunningError:
            self._json({"error": "публикация уже выполняется"}, 409)
            return
        except proxy_pool.ProxySelectionError as exc:
            self._json({"error": str(exc)}, 409)
            return
        self._json({"ok": True, "status": status}, 202)


class _QuietThreadingHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer, который не сыпет стектрейсом на разрыв соединения
    клиентом. Пока сервер занят (публикация), клиент (окно, браузер, телефон)
    иногда перестаёт ждать ответ и рвёт соединение сам — это уход клиента, а
    не авария сервера, и socketserver по умолчанию печатает его как
    ConnectionResetError/[WinError 10054] на всю консоль. Всё остальное
    (реальные ошибки обработчика) идёт как раньше — иначе в этом же шуме
    потерялись бы настоящие сбои."""

    def __init__(self, *args, **kwargs):
        self._phone_lock = threading.RLock()
        self._phone_servers = []
        super().__init__(*args, **kwargs)

    def phone_status(self) -> dict:
        owner = getattr(self, "phone_parent", self)
        with owner._phone_lock:
            servers = list(owner._phone_servers)
            connected = any(getattr(server, "phone_connected", False) for server in servers)
        return {"active": bool(servers), "supported": True,
                "connected": connected,
                "links": [f"http://{s.server_address[0]}:{s.server_address[1]}" for s in servers]}

    def phone_accepts(self, server) -> bool:
        with self._phone_lock:
            return server in self._phone_servers

    def set_phone_access(self, enabled: bool) -> None:
        owner = getattr(self, "phone_parent", self)
        if owner is not self:
            return owner.set_phone_access(enabled)
        with self._phone_lock:
            if enabled == bool(self._phone_servers):
                return
            if not enabled:
                stopped, self._phone_servers = self._phone_servers, []
                for server in stopped:
                    server.shutdown()
                    server.server_close()
                return
            addresses = phone_addresses()
            if not addresses:
                raise OSError("Не найден адрес компьютера в локальной сети")
            started = []
            try:
                for address in addresses:
                    server = type(self)((address, self.server_address[1]), self.RequestHandlerClass)
                    server.daemon_threads = True
                    server.require_auth = True
                    server.phone_parent = self
                    started.append(server)
                self._phone_servers = started
                for server in started:
                    threading.Thread(target=server.serve_forever, daemon=True).start()
            except OSError:
                for server in started:
                    server.server_close()
                raise

    def shutdown(self):
        self.set_phone_access(False)
        super().shutdown()

    def server_close(self):
        if not hasattr(self, "phone_parent"):
            self.set_phone_access(False)
        super().server_close()

    def get_request(self):
        request, address = super().get_request()
        if hasattr(self, "phone_parent"):
            self.phone_connected = True
        return request, address

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


def _primary_ip() -> str:
    """Адрес этого компьютера в сети. Соединение UDP не отправляет ни байта —
    система просто выбирает, через какой интерфейс шла бы связь."""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.2)
            s.connect(("8.8.8.8", 53))
            return s.getsockname()[0]
    except OSError:
        return ""


def phone_links(port: int) -> list:
    """Ссылки на интерфейс для телефона в той же сети."""
    ip = _primary_ip()
    return [f"http://{ip}:{port}"] if ip else []


def phone_addresses() -> list:
    """Local IPv4 addresses usable by a phone on the same network."""
    import ipaddress
    import socket
    candidates = []
    if sys.platform.startswith("linux"):
        import subprocess
        try:
            interfaces = json.loads(subprocess.check_output(
                ["ip", "-j", "-4", "addr", "show", "up"], timeout=2, stderr=subprocess.DEVNULL))
            for interface in interfaces:
                # Physical Ethernet/Wi-Fi interfaces have a broadcast address;
                # VPN tunnels are not useful to a phone on the local Wi-Fi.
                if "BROADCAST" in interface.get("flags", []) and not interface.get("ifname", "").startswith(("docker", "veth", "br-", "virbr")):
                    candidates.extend(row["local"] for row in interface.get("addr_info", [])
                                      if row.get("family") == "inet")
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    if not candidates:
        candidates.append(_primary_ip())
        try:
            candidates.extend(row[4][0] for row in socket.getaddrinfo(
                socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM))
        except OSError:
            pass
    networks = tuple(ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
    addresses = []
    for candidate in candidates:
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if any(address in network for network in networks) and candidate not in addresses:
            addresses.append(candidate)
    return addresses


def _no_console_freeze() -> None:
    """Выключить в консоли Windows режим выделения мышью (QuickEdit).

    Щелчок мышью по чёрному окну программы включает выделение, и пока оно
    висит, любая печать в консоль стоит на месте. Печатают почти все
    обработчики: загрузка фото сохраняла файл и зависала на строке в журнал,
    не ответив, а публикация и остальное вставали целиком до Esc в консоли.
    У собранного exe консоли нет — там выходим сразу."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return
        quick_edit, extended = 0x40, 0x80  # ENABLE_QUICK_EDIT_MODE, ENABLE_EXTENDED_FLAGS
        kernel32.SetConsoleMode(handle, (mode.value & ~quick_edit) | extended)
    except Exception:  # noqa: BLE001 — удобство, падать из-за него нельзя
        pass


def build_server(port: int = None, host: str = None,
                 auth: bool = True) -> ThreadingHTTPServer:
    """Собирает, но не запускает сервер — используется и здесь (CLI), и app.py
    (pywebview: сервер поднимается в фоновом потоке под нативным окном).

    host по умолчанию — из config.json (по умолчанию 0.0.0.0: слушает на всех
    интерфейсах). app.py передаёт его явно: 127.0.0.1, а с доступом с
    телефона — 0.0.0.0.

    auth — спрашивать ли пароль (modules/auth.py) с чужих адресов; с самого
    компьютера его не спрашивают никогда (Handler._auth_required)."""
    _no_console_freeze()
    # журнал работы: перехватываем печать модулей, чтобы UI показывал не
    # только свои запросы, но и вход, смену IP, публикацию постов и причины
    # отказов (см. modules/eventlog.py и GET /api/logs)
    from modules import eventlog
    eventlog.attach_stdout()
    # «схему в строке прокси не называли» — знание того, кто строку разбирал,
    # а не config: возвращаем его до первого дела с прокси (см.
    # _restore_scheme_knowledge), иначе тип строки после перезапуска снова
    # угадывался бы
    _restore_scheme_knowledge()
    # итог каждой чистки постов (ручной и внутри кампании) правит числа студии
    from modules import purge
    purge.on_result(_studio_note_purge)
    port = port or int(config.get("port") or 8740)
    host = host or str(config.get("host") or "127.0.0.1")
    httpd = _QuietThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    httpd.require_auth = bool(auth)
    return httpd


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else None
    host = sys.argv[2] if len(sys.argv) > 2 else None
    httpd = build_server(port, host)
    bound_host, actual_port = httpd.server_address
    if bound_host not in ("127.0.0.1", "localhost"):
        print(f"[server] ВНИМАНИЕ: слушает {bound_host} — доступно с других "
              f"устройств сети, не только с этой машины")
    print(f"[server] http://{bound_host}:{actual_port}  (статика: ui/, API: /api/*)")
    print(f"[server] config: {config.CONFIG_FILE} (live-чтение при каждом запросе; "
          f"host/port тоже оттуда, если не заданы аргументом)")
    print("[server] это dev-режим (ссылку открывать вручную); "
          "пользовательский запуск — python app.py (нативное окно)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[server] остановлен")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
