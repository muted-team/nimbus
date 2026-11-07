"""Account registry and validated client imports."""
import json
import re
import threading
from pathlib import Path

from . import paths

BASE = Path(__file__).resolve().parent.parent
ACCOUNTS_FILE = BASE / "accounts.json"
# забаненные/удалённые аккаунты, вынесенные из accounts.json: не участвуют в
# публикации, но не потеряны совсем — лежат тут со временем и причиной бана,
# формат {"accounts": [{...запись..., "banned_at", "ban_reason"}]}.
BANNED_FILE = BASE / "banned.json"

# add_account может зваться из HTTP-потоков, _rotate_to_end кампании —
# из фонового потока: одновременные записи файла сериализуем локом.
# RLock, не Lock: add/remove сами берут _lock и зовут _write_json,
# который берёт его повторно (реентерабельность обязательна).
_lock = threading.RLock()


def _read_raw(path: Path = None) -> dict:
    """accounts.json (или другой файл зоны, например banned.json) как dict;
    нет/битый файл -> {"accounts": []}."""
    try:
        raw = json.loads(paths.here(path or ACCOUNTS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"accounts": []}
    if not isinstance(raw, dict) or not isinstance(raw.get("accounts"), list):
        return {"accounts": []}
    return raw


def _write_json(path: Path, data: dict) -> None:
    """Атомарная запись JSON-файла зоны целиком (pretty-print, utf-8).

    Через общий config.write_text_atomic — тот же приём, что у config.save
    (временный файл рядом, подмена одним движением), и одна реализация на всю
    программу. Помощник принимает готовый текст, поэтому переводы строк в
    файлах аккаунтов не едут.

    _lock (RLock) берётся здесь же: add/remove/rotate/mark зовут запись уже
    под ним, а повторный вход RLock разрешает.
    """
    from . import config
    with _lock:
        config.write_text_atomic(
            path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _restore_json(path: Path, content: bytes) -> None:
    """Вернуть точные байты реестра, если действие с файлами сессии не удалось."""
    tmp = path.with_name("%s.%d.tmp" % (path.name, threading.get_ident()))
    try:
        tmp.write_bytes(content)
        tmp.replace(path)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def _has_session(username: str) -> bool:
    """Вошли ли в аккаунт: куки на месте или строка состояния у сервера."""
    from . import client_session as SM
    return SM.has_session(username)


def list_accounts() -> list:
    """Список аккаунтов для UI/API: [{"username", "has_session", "has_totp",
    "has_email", "avatar", "profile", "region", "lang"}].

    Пароль/TOTP не возвращаются. has_session — существует ли файл сессии
    sessions/<username>.json. has_totp/has_email — откуда брать код
    подтверждения (в списке аккаунтов это щит и конверт у логина), сами
    секреты наружу не уходят. avatar — когда сохранена аватарка (unix-время)
    или None; саму картинку отдаёт GET /api/avatars (modules/avatars.py).
    profile — профиль из data.db с суммами по постам (тот же JSON, что у
    GET /api/profiles/@<имя>) или None, если профиль ещё не забирали.
    region/lang — настоящий регион и язык аккаунта из кук уже сохранённой
    сессии (session_manager.session_facts), не из строки, которой аккаунт
    добавляли: TikTok подписывает часть этих кук сам, подделать нельзя.
    Нет сессии или в ней нет нужной куки — None. idc из тех же фактов сюда
    не выводится — он только для диагностики.
    Прокси у аккаунта больше нет — ротацией прокси занимается кампания
    (config.proxies).
    """
    from . import avatars, profiles, client_session
    stamps = avatars.versions()
    known = profiles.summaries()
    out = []
    for acc in _read_raw()["accounts"]:
        if isinstance(acc, dict) and acc.get("username"):
            username = str(acc["username"])
            facts = client_session.session_facts(username)
            out.append({"username": username,
                        "has_session": _has_session(username),
                        # источник 2FA-кода — без самих секретов
                        "has_totp": bool(acc.get("totp_secret")),
                        "has_email": bool(acc.get("email") and acc.get("email_password")),
                        "avatar": stamps.get(username),
                        "profile": known.get(username),
                        "region": facts["region"],
                        "lang": facts["lang"]})
    return out


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_B32_RE = re.compile(r"^([A-Z2-7]+|[a-z2-7]+)$")   # base32 в одном регистре
_PLAIN_ID_RE = re.compile(r"^[a-z0-9._]{2,24}$")    # логин: строчные/цифры, без спецсимволов
# Длины 2FA-секрета: base32 от ключа стандартного размера — 80, 128, 160 и
# 256 бит. Промежуточных не бывает, и это единственный надёжный признак:
# по набору символов секрет от логина той же формы не отличить.
_TOTP_LENGTHS = (16, 26, 32, 52)
# Токен, годный на роль логина. Правило самого TikTok: юзернейм — только
# буквы, цифры, '_' и '.', длиной 2-24 символа. Ни '$', ни '!', ни '-' в нём
# не бывает, поэтому `gjfnix054$` логином не считается ни при каком порядке
# полей. Верхняя граница 24 заодно разводит логин с 2FA-секретом: секрет на
# 26, 32 или 52 символа юзернеймом быть не может.
# `\w` вместо `A-Za-z0-9_` — логин вне ASCII: иначе такой токен уходил
# в разбор по виду и менялся местами с паролем.
_LOGIN_RE = re.compile(r"^@?[\w.]{2,24}$")


def _looks_totp(tok: str) -> bool:
    """Похоже на 2FA-секрет: одна раскладка base32 и РОВНО стандартная длина
    ключа (не «16 и больше» — так логин принимался за секрет).

    Длина считается от размера ключа: 16 символов = 80 бит (Google
    Authenticator), 26 = 128 бит (минимум RFC 4226), 32 = 160 бит (обычная
    рекомендация RFC 4226/6238), 52 = 256 бит. Промежуточной длины у секрета
    не бывает: 17 символов base32 просто не декодируются (длина ≡ 1 по модулю
    8), а логин такой длины из букв и цифр 2-7 — сколько угодно.

    16 и 26 символов принимаем только если есть цифра 2–7 (отсекает
    слова-логины); 32+ — принимаем и без цифр."""
    if len(tok) not in _TOTP_LENGTHS or not _B32_RE.match(tok):
        return False
    return len(tok) >= 32 or bool(re.search(r"[2-7]", tok))


def _looks_login(tok: str) -> bool:
    """Токен, годный на роль логина: буквы любого алфавита, цифры, ._- (можно
    с ведущим '@').

    Шире `_PLAIN_ID_RE`: настоящий логин бывает с заглавными и точкой
    (`Kate_2024`, `Anna.K`), а прежний разбор по виду такие не признавал; вне
    ASCII (`Катя`) тоже признаётся логином. Здесь это только признак
    «первая часть строки похожа на логин» — сам логин берётся по позиции, а не
    по виду."""
    return bool(_LOGIN_RE.match(tok))


def _parse_account_line(line: str):
    """Достаёт аккаунт из строки. Разделители любые (| : ; , пробел, таб —
    вперемешку).

    Первые две части строки — логин и пароль, по ПОЗИЦИИ, без угадывания:
    `Kate_2024:kate2024:2FA` и `coiijf2i3:coiijf2i3:2FA` разбираются по
    порядку, даже когда пароль выглядит проще логина.

    Разбор по ВИДУ — запасной путь: он в ходу, когда первая часть вовсе не
    похожа на логин (строка начинается с почты или с 2FA-секрета), то есть
    при произвольном порядке полей:
      - email          — есть '@' и точка после ('user@mail.ru');
      - 2fa            — base32 в одном регистре и РОВНО стандартная длина
                         ключа: 16, 26, 32 или 52 символа (_looks_totp);
      - логин          — токен только из строчных/цифр/._ (можно с ведущим
                         '@'); при нескольких — первый. Такого нет — первый,
                         который TikTok вообще примет за юзернейм (буквы,
                         цифры, '_' и '.'): логин вне ASCII (`Катя`) с паролем
                         в запасном пути не различить по виду — разобрано
                         осознанно, по позиции такие строки читает
                         правило выше. Годного на юзернейм токена нет вовсе —
                         строка не разбирается;
      - регион         — двухбуквенный код вроде `US` отбрасывается, но не
                         сохраняется: строке продавца доверять нельзя, настоящий
                         регион берётся только из подписанных TikTok cookies;
      - пароли         — оставшиеся токены. Если есть почта и паролей два —
                         пароль почты это тот, что стоит СРАЗУ ПОСЛЕ адреса
                         почты (обычная форма комбо
                         'user:pass:email:emailpass'), второй — пароль аккаунта.
    Итог dict: {username, password, totp_secret?, email?, email_password?}.
    Короткий формат — логин и пароль. В расширенном формате распознаётся
    источник кода: 2FA-секрет либо почта с паролем почты. Иначе None.
    """
    raw = [t for t in re.split(r"[\s|:;,]+", line.strip()) if t]
    if len(raw) == 2:
        # No source of a code is required until TikTok asks for one. In this
        # short format the second token is always a password, never a TOTP key.
        if _looks_login(raw[0]):
            return {"username": raw[0].lstrip("@"), "password": raw[1]}
        return None
    if len(raw) < 3:
        return None

    # (индекс, токен) — индекс нужен, чтобы понять, какой пароль относится к почте
    tokens = list(enumerate(raw))
    email = email_idx = None
    for idx, t in tokens:
        if _EMAIL_RE.match(t):
            email, email_idx = t, idx
            break

    # Секрет выбираем среди ВСЕХ подходящих, а не берём первый попавшийся:
    # 16 символов — длина спорная, столько же бывает и у логина. Кандидат на
    # 26/32/52 символа не может быть ни логином (у юзернейма максимум 24), ни
    # паролем (у пароля максимум 20) — такой и берём. Спорный берём только
    # если другого нет, и не с первого места: там по правилу владельца логин.
    cands = [idx for idx, t in tokens if idx != email_idx and _looks_totp(t)]
    totp_idx = min(cands, key=lambda i: (len(raw[i]) <= 24, i == 0, i), default=None)
    totp = raw[totp_idx].upper() if totp_idx is not None else None

    taken = {i for i in (email_idx, totp_idx) if i is not None}  # логином их уже не возьмём
    rest = [it for it in tokens if it[0] not in taken]  # (индекс, токен) — всё, что не почта/2fa

    first_idx, first_tok = tokens[0]
    # правило владельца: первая часть строки — логин, вторая — пароль, по
    # позиции, а не по виду
    positional_login = first_idx not in taken and _looks_login(first_tok)

    if not rest:
        return None

    if positional_login:
        # правило владельца: первая часть строки — логин, вторая — пароль,
        # по позиции, а не по виду
        login_idx = first_idx
    else:
        # запасной путь (строка начинается с почты/2fa): порядок произвольный —
        # логин первый токен-идентификатор, иначе первый, который TikTok вообще
        # примет за юзернейм. Годного нет — строку не разбираем: раньше тут
        # брался «первый оставшийся, каким бы он ни был», и в логин уезжал
        # пароль со спецсимволами (`gjfnix054$`).
        login_idx = next((it[0] for it in rest
                          if _PLAIN_ID_RE.match(it[1].lstrip("@"))),
                         next((it[0] for it in rest if _looks_login(it[1])), None))
        if login_idx is None:
            return None
    username = raw[login_idx].lstrip("@")
    pwd_items = [it for it in rest if it[0] != login_idx]
    if not username or not pwd_items:
        return None

    # Регион из комбо не сохраняем принципиально: он может быть выдуманным.
    # Убираем похожий на ISO-код токен только когда рядом есть другой кандидат
    # на пароль — единственное значение `US` оставляем, чтобы разбор не решал
    # за человека, что это точно не пароль.
    if len(pwd_items) > 1:
        without_region = [it for it in pwd_items
                          if not re.fullmatch(r"[A-Z]{2}", it[1])]
        if without_region:
            pwd_items = without_region

    email_password = None
    if email is not None and not totp and len(pwd_items) >= 2:
        # пароль почты — ближайший пароль ПОСЛЕ адреса почты (обычная форма);
        # нет такого — берём последний из паролей
        after = [it for it in pwd_items if it[0] > email_idx]
        ep_item = min(after, key=lambda it: it[0]) if after else pwd_items[-1]
        email_password = ep_item[1]
        pwd_items = [it for it in pwd_items if it[0] != ep_item[0]]

    if totp and len(pwd_items) > 1:
        # При TOTP почта не является источником кода и её пароль угадывать не
        # надо. Пароль аккаунта — ближайшее поле после логина (обычный порядок
        # email|login|password|region|2fa); если его нет, ближайшее перед ним.
        after_login = [it for it in pwd_items if it[0] > login_idx]
        password_item = (min(after_login, key=lambda it: it[0]) if after_login
                         else max(pwd_items, key=lambda it: it[0]))
        password = password_item[1]
    else:
        password = " ".join(t for _, t in pwd_items) if pwd_items else None
    if not password:
        return None

    # источник кода обязателен: 2FA-секрет ИЛИ почта с паролем почты
    if not totp and not (email and email_password):
        return None

    entry = {"username": username, "password": password}
    if totp:
        entry["totp_secret"] = totp
    if email:
        entry["email"] = email
    if email_password:
        entry["email_password"] = email_password
    return entry


def add_accounts_bulk(text: str) -> dict:
    """Массовое добавление: по одному аккаунту на строку. Строку разбирает
    _parse_account_line: первые две части — логин и пароль по порядку, дальше
    поля по виду. Достаточно логина и пароля; источник кода необязателен.
    JSON с куки импортируется целиком после проверки владельца сервером.
    Пустые строки и строки с '#' пропускаются.

    Ответ — {"added": [username, ...], "updated": [{"username", "replaced"}],
    "errors": [{"line", "reason"}]}; ключа "updated" нет, когда перезаписей
    не было. Ни в одном ключе нет содержимого строки: строка несёт пароль и
    2FA-секрет, поэтому ошибка называет только номер строки и причину
    (какая именно строка не разобралась, видно по номеру в поле ввода).

    Существующий username обновляется (не дубль): он уходит в "updated" и в
    "added" не попадает. Каждая запись updated — {"username", "replaced"}:
    перечислены поля, значение которых строка заменила (пароль, 2FA-секрет,
    почта...). Поля, которых в строке нет, у аккаунта сохраняются и заменой не
    считаются.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("вставьте логин с паролем или JSON с куки TikTok")
    if text.lstrip().startswith(('[', '{')):
        return _add_cookie_account(text)

    added, updated, errors = [], [], []
    with _lock:
        raw = _read_raw()
        accounts = raw["accounts"]
        for i, rawline in enumerate(text.splitlines(), start=1):
            line = rawline.strip()
            if not line or line.startswith("#"):
                continue
            entry = _parse_account_line(line)
            if entry is None:
                errors.append({"line": i,
                               "reason": "не удалось разобрать логин и пароль; "
                                         "2FA-секрет или почта с паролем необязательны"})
                continue
            username = entry["username"]
            idx = next((j for j, a in enumerate(accounts)
                        if isinstance(a, dict) and a.get("username") == username), None)
            if idx is None:
                accounts.append(entry)
                added.append(username)
            else:
                # поля, которых нет в строке, но были у аккаунта, сохраняем
                # (короткий формат не должен затирать почту/2FA)
                old = accounts[idx]
                for k in ("email", "email_password", "totp_secret"):
                    if k not in entry and isinstance(old.get(k), str) and old[k].strip():
                        entry[k] = old[k]
                replaced = sorted(k for k in entry
                                  if k != "username" and old.get(k) != entry[k])
                accounts[idx] = entry
                updated.append({"username": username, "replaced": replaced})
        if added or updated:
            _write_json(paths.here(ACCOUNTS_FILE), raw)
    result = {"added": added, "updated": updated, "errors": errors}
    if not updated:
        del result["updated"]
    return result


def _add_cookie_account(text: str) -> dict:
    """Save only a server-confirmed owner and token; preserve saved credentials."""
    from . import client_session, cloud, proxy_pool, remote
    # Invalid JSON must never fall through to credential-line guessing.
    client_session.normalize_cookie_import(text)
    account_path = paths.here(ACCOUNTS_FILE)
    with _lock:
        before_accounts = account_path.read_bytes() if account_path.exists() else None
    try:
        verified = cloud.import_cookies(text)
    except proxy_pool.NoAliveProxy:
        raise ValueError('Нет рабочего прокси для проверки куки') from None
    except remote.RemoteError:
        raise ValueError('Сервер не подтвердил сессию по куки') from None
    username, token = verified['username'], verified['state']
    with cloud._lock(username), _lock:
        current_accounts = account_path.read_bytes() if account_path.exists() else None
        if current_accounts != before_accounts:
            raise ValueError('Список аккаунтов изменился во время проверки куки')
        raw = _read_raw()
        existed = any(isinstance(a, dict) and a.get('username') == username for a in raw['accounts'])
        if not existed:
            raw['accounts'].append({'username': username})
        path = client_session.state_file(username)
        generation = verified.get('generation', client_session.state_generation(path))
        previous = verified.get('previous_state', path.read_bytes() if path.exists() else None)
        client_session.commit_cookie_import(
            path, token, generation, previous,
            lambda: _write_json(account_path, raw), verified.get('device_update'))
    if existed:
        return {'added': [], 'updated': [{'username': username, 'replaced': ['session']}], 'errors': []}
    return {'added': [username], 'errors': []}


def add_account(data: dict) -> dict:
    """Добавляет аккаунт или обновляет существующий с тем же username.

    data: {username, password, totp_secret?, email?, email_password?}.
    username и есть логин. Обязательны username и password; источник кода
    (totp_secret либо email вместе с email_password) необязателен. Все — непустые строки,
    иначе ValueError (текст человеческий, без секретов). Перезапись
    существующего username — обновление полей (не дубликат). Возвращает
    запись БЕЗ секретов: {"username", "has_email", "has_session"}.
    """
    if not isinstance(data, dict):
        raise ValueError("ожидается JSON-объект с полями username и password")
    for field in ("username", "password"):
        v = data.get(field)
        if not isinstance(v, str) or not v.strip():
            raise ValueError(f"{field} обязателен и должен быть непустой строкой")

    def _clean(field):
        v = data.get(field)
        if v is None:
            return None
        if not isinstance(v, str) or not v.strip():
            raise ValueError(f"{field} должен быть непустой строкой или отсутствовать")
        return v.strip()

    totp = _clean("totp_secret")
    email = _clean("email")
    email_password = _clean("email_password")
    entry = {"username": data["username"], "password": data["password"]}
    if totp:
        entry["totp_secret"] = totp
    if email:
        entry["email"] = email
    if email_password:
        entry["email_password"] = email_password

    username = entry["username"]
    with _lock:
        raw = _read_raw()
        accounts = raw["accounts"]
        idx = next((i for i, a in enumerate(accounts)
                    if isinstance(a, dict) and a.get("username") == username), None)
        if idx is None:
            accounts.append(entry)
        else:
            accounts[idx] = entry
        _write_json(paths.here(ACCOUNTS_FILE), raw)

    return {"username": username,
            "has_email": bool(entry.get("email") and entry.get("email_password")),
            "has_session": _has_session(username)}


def update_account(username: str, patch: dict) -> dict:
    """Ручная правка одного аккаунта — пароль сменился, логин определился

    неверно при массовой вставке и т.п. (не путать с add_account: там
    приходит уже готовая запись целиком, а сюда — только то, что человек
    поправил).

    patch: {username?, password?, totp_secret?, email?, email_password?} —
    непустые строки; поле отсутствует или не прислано -> значение
    аккаунта не трогаем. Пустая строка ЧИСТИТ поле (кроме username/password —
    они обязательны всегда): так снимается totp_secret при переходе на почту
    и наоборот, и email/email_password, когда их больше нет. Итоговая
    запись обязана сохранить логин и пароль либо импортированную сессию;
    источник кода необязателен. Иначе ValueError, ничего не меняется.

    Смена username — это переименование существующей записи (jar сессии и
    накопленные profile/avatar/posts в data.db переезжают на новое имя, а не
    теряются); столкновение с уже существующим другим username — ValueError.

    Возвращает запись БЕЗ секретов, как list_accounts(): {"username",
    "has_session", "has_totp", "has_email", "avatar", "profile"}.
    """
    if not isinstance(username, str) or not username:
        raise ValueError("нужен username существующего аккаунта")
    if not isinstance(patch, dict):
        raise ValueError("ожидается JSON-объект с правками")

    def _field(key, required=False):
        """Строка или None (поле не прислано) либо "" (поле сброшено)."""
        if key not in patch:
            return None
        v = patch[key]
        if v is None:
            v = ""
        if not isinstance(v, str):
            raise ValueError(f"{key} должен быть строкой")
        v = v.strip()
        if required and not v:
            raise ValueError(f"{key} не может быть пустым")
        return v

    from . import config

    new_username = _field("username", required=True)
    password = _field("password")
    totp = _field("totp_secret")
    email = _field("email")
    email_password = _field("email_password")

    with _lock:
        raw = _read_raw()
        accounts = raw["accounts"]
        idx = next((i for i, a in enumerate(accounts)
                    if isinstance(a, dict) and a.get("username") == username), None)
        if idx is None:
            raise ValueError(f"аккаунт {username} не найден")
        old = accounts[idx]

        final_username = new_username if new_username is not None else username
        if final_username != username and any(
                isinstance(a, dict) and a.get("username") == final_username
                for a in accounts):
            raise ValueError(f"аккаунт {final_username} уже существует")

        final_password = password if password is not None else old.get("password")
        if not final_password and (old.get('password') or not _has_session(username)):
            raise ValueError('Для аккаунта без сохранённой сессии нужен пароль')
        entry = {"username": final_username}
        if final_password:
            entry['password'] = final_password
        for key, incoming in (("totp_secret", totp), ("email", email),
                              ("email_password", email_password)):
            value = incoming if incoming is not None else old.get(key)
            if value:
                entry[key] = value

        account_path = paths.here(ACCOUNTS_FILE)
        original_accounts = account_path.read_bytes() if final_username != username else b""
        accounts[idx] = entry
        _write_json(account_path, raw)
        if final_username != username:
            from . import client_session
            try:
                client_session.rename_jar(username, final_username)
            except OSError:
                _restore_json(account_path, original_accounts)
                raise

        if config.get("default_account") == username and final_username != username:
            try:
                config.update({"default_account": final_username})
            except OSError:
                pass  # аккаунт уже переименован — дефолт просто устареет

    if final_username != username:
        from . import avatars
        avatars.rename(username, final_username)

    from . import avatars, profiles
    return {"username": final_username,
            "has_session": _has_session(final_username),
            "has_totp": bool(entry.get("totp_secret")),
            "has_email": bool(entry.get("email") and entry.get("email_password")),
            "avatar": avatars.versions().get(final_username),
            "profile": profiles.summaries().get(final_username)}


def _exists(username: str) -> bool:
    with _lock:
        return any(isinstance(account, dict) and account.get("username") == username
                   for account in _read_raw()["accounts"])


def _keep_device(username: str, new_device: bool, strict: bool = True) -> None:
    """Перед стиранием входа: без смены устройства компьютер аккаунта
    сохраняется (cloud.keep_device) — следующий вход будет с ним. strict —
    сбой сети отменяет действие (пользователь просил оставить компьютер, и
    молча его потерять нельзя); без strict — только пишется в лог (бан посреди
    кампании не должен вставать из-за сервера)."""
    if new_device:
        return
    from . import client_device, client_session, cloud, remote
    for profile in client_device.BROWSER_PROFILES:
        with client_device.use_browser_profile(profile):
            try:
                if not client_session.has_session(username):
                    continue
                cloud.keep_device(username)
            except (remote.RemoteError, OSError) as exc:
                if strict:
                    raise
                print(f"[accounts] {username}: компьютер аккаунта не сохранён ({exc})")


def remove_account(username: str, new_device: bool = False) -> bool:
    """Убирает аккаунт из accounts.json и удаляет его файл cookies.

    Возвращает True, если аккаунт был найден и удалён; False — такого
    username в файле нет (файл при этом не трогается). Отсутствующий jar —
    не ошибка. new_device — стереть и компьютер аккаунта; без него он
    остаётся, и аккаунт, добавленный снова, войдёт с той же машины.
    """
    if not isinstance(username, str) or not username or not _exists(username):
        return False
    _keep_device(username, new_device)
    from . import client_session as SM
    with _lock:
        raw = _read_raw()
        accounts = raw["accounts"]
        idx = next((i for i, a in enumerate(accounts)
                    if isinstance(a, dict) and a.get("username") == username), None)
        if idx is None:
            return False
        account_path = paths.here(ACCOUNTS_FILE)
        original_accounts = account_path.read_bytes()
        accounts.pop(idx)
        _write_json(account_path, raw)
        try:
            SM.clear_session(username, new_device=new_device)
        except OSError:
            _restore_json(account_path, original_accounts)
            raise
    from . import avatars, eventlog
    avatars.remove(username)  # и аватарку, и профиль с постами
    eventlog.say("аккаунт удалён из списка, компьютер %s"
                 % ("стёрт" if new_device else "сохранён"), "warn", username, "accounts")
    return True


def clear_session(username: str, new_device: bool = False) -> dict:
    """Очищает локальную авторизацию, не удаляя аккаунт из списка.

    Удаляется только сохранённый jar и связанный с ним кэш живости; сетевых
    запросов нет. Пароль, источник кода, профиль, аватарка и история
    публикаций остаются, поэтому аккаунт можно сразу авторизовать заново.
    Повторный вызов после уже выполненной очистки успешен и возвращает
    files_removed=0.

    Возвращает {username, session_cleared, files_removed}. Неизвестный
    аккаунт — ValueError: нельзя по произвольному имени удалять файлы из
    sessions, даже несмотря на безопасное преобразование имени файла.

    new_device — стереть и компьютер аккаунта (следующий вход — с новым);
    без него компьютер сохраняется запросом к серверу, и сбой сети —
    RemoteError: вход тогда не стирается.
    """
    if not isinstance(username, str) or not username:
        raise ValueError("нужен username существующего аккаунта")
    if not _exists(username):
        raise ValueError(f"аккаунт {username} не найден")

    _keep_device(username, new_device)
    from . import client_session, eventlog
    removed = client_session.clear_session(username, new_device=new_device)
    eventlog.say("вход забыт, компьютер %s" % ("стёрт" if new_device else "сохранён"),
                 "warn", username, "accounts")
    return {"username": username, "session_cleared": True,
            "files_removed": removed}


def mark_banned(username: str, reason: str = "", keep_session: bool = False) -> bool:
    """Убирает аккаунт из accounts.json (он забанен/удалён у TikTok — вход не
    выйдет) и переносит его запись в banned.json со временем и причиной.

    Возвращает True, если аккаунт был в списке и перенесён; False — такого
    username в accounts.json нет. Секреты остаются в записи (banned.json тот
    же приватный файл, что accounts.json), чтобы аккаунт можно было вернуть
    вручную, если бан оказался ошибкой. Файл sessions/<имя>.json и
    аватарка удаляются — сессия всё равно мёртва. keep_session=True — оставить
    их: аккаунт приостановлен, а не удалён (login.KEEP_SESSION_CODES), и после
    снятия приостановки «Вернуть» отдаст его с живой сессией."""
    import time
    if not isinstance(username, str) or not username:
        return False
    with _lock:
        raw = _read_raw()
        accounts = raw["accounts"]
        idx = next((i for i, a in enumerate(accounts)
                    if isinstance(a, dict) and a.get("username") == username), None)
        if idx is None:
            return False
        entry = accounts.pop(idx)
        _write_json(paths.here(ACCOUNTS_FILE), raw)
        banned = _read_raw(BANNED_FILE)
        # повторный бан того же имени не плодит дублей: обновляем запись
        banned["accounts"] = [a for a in banned["accounts"]
                              if not (isinstance(a, dict) and a.get("username") == username)]
        banned["accounts"].append({**entry, "banned_at": int(time.time()),
                                   "ban_reason": (reason or "").strip()})
        _write_json(paths.here(BANNED_FILE), banned)
    if keep_session:
        return True
    # компьютер остаётся: «Вернуть» и новый вход — с той же машины
    _keep_device(username, new_device=False, strict=False)
    from . import client_session as SM
    try:
        SM.clear_session(username)  # и куки, и строку состояния у сервера
    except OSError:
        pass
    from . import avatars
    avatars.remove(username)
    return True


def list_banned() -> list:
    """Забаненные аккаунты для UI: [{"username", "banned_at", "ban_reason"}]
    (без секретов), новые сверху."""
    out = []
    for a in _read_raw(BANNED_FILE)["accounts"]:
        if isinstance(a, dict) and a.get("username"):
            out.append({"username": str(a["username"]),
                        "banned_at": a.get("banned_at"),
                        "ban_reason": a.get("ban_reason") or ""})
    out.sort(key=lambda a: a.get("banned_at") or 0, reverse=True)
    return out


def restore_banned(username: str) -> bool:
    """Возвращает аккаунт из banned.json обратно в accounts.json (если бан
    оказался ошибкой). True — вернули; False — такого нет среди забаненных."""
    if not isinstance(username, str) or not username:
        return False
    with _lock:
        banned = _read_raw(BANNED_FILE)
        idx = next((i for i, a in enumerate(banned["accounts"])
                    if isinstance(a, dict) and a.get("username") == username), None)
        if idx is None:
            return False
        entry = banned["accounts"].pop(idx)
        entry.pop("banned_at", None)
        entry.pop("ban_reason", None)
        _write_json(paths.here(BANNED_FILE), banned)
        raw = _read_raw()
        if not any(isinstance(a, dict) and a.get("username") == username
                   for a in raw["accounts"]):
            raw["accounts"].append(entry)
            _write_json(paths.here(ACCOUNTS_FILE), raw)
    return True


def rotate_to_end(username: str) -> None:
    """Перекладывает запись username в конец списка accounts (ротация
    очереди кампании: следующий запуск начнёт с того, кто дольше всех ждал).

    Под тем же _lock, что и все остальные записи accounts.json —
    параллельные воркеры кампании не затирают ротации друг друга. Ошибки
    чтения/записи печатаются и глотаются (ротация — не критичная операция,
    кампания не должна падать из-за неё)."""
    if not isinstance(username, str) or not username:
        return
    with _lock:
        try:
            raw = _read_raw()
        except (OSError, ValueError) as exc:
            print(f"[accounts] не удалось прочитать accounts.json для ротации: "
                  f"{type(exc).__name__}: {exc}")
            return
        accounts = raw.get("accounts")
        if not isinstance(accounts, list):
            return
        idx = next((i for i, a in enumerate(accounts)
                    if isinstance(a, dict) and a.get("username") == username), None)
        if idx is None:
            return
        accounts.append(accounts.pop(idx))
        try:
            _write_json(paths.here(ACCOUNTS_FILE), raw)
        except OSError as exc:
            print(f"[accounts] не удалось записать accounts.json после ротации "
                  f"{username}: {type(exc).__name__}: {exc}")


def secrets_of(username: str) -> dict:
    """Пароль и источник кода аккаунта — для формы ручной правки (GET

    /api/accounts/secrets), единственное сознательное исключение из правила
    «секреты наружу не отдаются» (см. правила модуля выше): владелец должен
    видеть, что сейчас сохранено, чтобы свериться посимвольно и найти
    опечатку. НЕ логировать возвращённое значение и не подмешивать ни в
    list_accounts(), ни в любой ответ, который уходит массово по всем
    аккаунтам.

    Возвращает {"password", "totp_secret", "email", "email_password"} —
    только то, что реально сохранено (ключа нет, если поля не было).
    ValueError — такого username нет.
    """
    if not isinstance(username, str) or not username:
        raise ValueError("нужен username существующего аккаунта")
    for acc in _read_raw()["accounts"]:
        if isinstance(acc, dict) and acc.get("username") == username:
            return {k: acc[k] for k in ("password", "totp_secret", "email", "email_password")
                    if isinstance(acc.get(k), str) and acc[k]}
    raise ValueError(f"аккаунт {username} не найден")


def load_account(name: str = None) -> dict:
    """Полная запись аккаунта (с секретами — только для внутреннего
    использования: login/batch_publish; наружу НИКОГДА).

    name=None -> аккаунт по умолчанию из config (default_account):
    пусто/не задан -> ValueError. Файла нет -> создаётся {"accounts": []},
    дальше обычный поиск. Не найден -> ValueError (не StopIteration!).
    """
    from . import config
    if name is None:
        name = config.get("default_account")
        if not name or not str(name).strip():
            raise ValueError("аккаунт по умолчанию не выбран — "
                             "добавьте аккаунт и войдите")
    for acc in _read_raw()["accounts"]:
        if isinstance(acc, dict) and acc.get("username") == name:
            return acc
    raise ValueError(f"аккаунт {name} не найден — "
                     "добавьте его в разделе «Аккаунты»")
