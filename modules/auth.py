"""Local interface password and session authentication."""
import hashlib
import hmac
import secrets
import threading
import time
from http.cookies import SimpleCookie

from . import config

COOKIE = "tt_auth"
COOKIE_MAX_AGE = 365 * 24 * 3600
MIN_LEN = 6
ITERATIONS = 200_000

FAIL_LIMIT = 10
FAIL_WINDOW = 600

_fails_lock = threading.Lock()
_fails = {}  # ip -> [время неудачи, ...] за последние FAIL_WINDOW секунд


def _section() -> dict:
    data = config.get("auth")
    return data if isinstance(data, dict) else {}


def enabled() -> bool:
    """Задан ли пароль."""
    return bool(_section().get("password_hash"))


def _hash(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = _hash(password, salt, ITERATIONS)
    return "pbkdf2_sha256$%d$%s$%s" % (ITERATIONS, salt.hex(), digest.hex())


def check_password(password) -> bool:
    stored = _section().get("password_hash")
    if not isinstance(password, str) or not isinstance(stored, str):
        return False
    try:
        algo, iterations, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        got = _hash(password, bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(got, bytes.fromhex(digest))
    except (ValueError, TypeError):
        return False


def validate(password) -> str:
    """Причина, по которой пароль не годится, или пустая строка."""
    if not isinstance(password, str) or len(password) < MIN_LEN:
        return "пароль — не короче %d знаков" % MIN_LEN
    if len(password) > 256:
        return "пароль — не длиннее 256 знаков"
    if password != password.strip():
        return "пароль не должен начинаться или кончаться пробелом"
    return ""


def set_password(password: str) -> None:
    """Записать новый пароль. ValueError — пароль не годится."""
    why = validate(password)
    if why:
        raise ValueError(why)
    section = _section()
    patch = {"password_hash": hash_password(password)}
    if not section.get("secret"):
        patch["secret"] = secrets.token_hex(32)
    config.update({"auth": patch})


def clear_password() -> None:
    """Снять пароль. Секрет куки меняется: входы на других устройствах гаснут
    и при новом пароле не оживут."""
    config.update({"auth": {"password_hash": None, "secret": secrets.token_hex(32)}})


def token() -> str:
    """Значение куки для текущего пароля; пустая строка — пароль не задан."""
    section = _section()
    digest = section.get("password_hash")
    if not digest:
        return ""
    secret = section.get("secret")
    if not secret:
        secret = secrets.token_hex(32)
        config.update({"auth": {"secret": secret}})
    return hmac.new(str(secret).encode("utf-8"), str(digest).encode("utf-8"),
                    hashlib.sha256).hexdigest()


def cookie_ok(header) -> bool:
    """Подходит ли кука из заголовка Cookie к текущему паролю."""
    if not header:
        return False
    expected = token()
    if not expected:
        return False
    try:
        jar = SimpleCookie()
        jar.load(header)
    except Exception:  # noqa: BLE001 — битый заголовок = не вошёл
        return False
    morsel = jar.get(COOKIE)
    return bool(morsel) and hmac.compare_digest(morsel.value, expected)


def set_cookie_header(secure: bool) -> str:
    value = "%s=%s; Path=/; HttpOnly; SameSite=Lax; Max-Age=%d" % (
        COOKIE, token(), COOKIE_MAX_AGE)
    return value + ("; Secure" if secure else "")


def clear_cookie_header(secure: bool) -> str:
    value = "%s=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0" % COOKIE
    return value + ("; Secure" if secure else "")


def _recent(ip: str, now: float) -> list:
    stamps = [t for t in _fails.get(ip, []) if now - t < FAIL_WINDOW]
    if stamps:
        _fails[ip] = stamps
    else:
        _fails.pop(ip, None)
    return stamps


def blocked_for(ip: str) -> int:
    """Сколько секунд этому адресу ещё нельзя пробовать; 0 — можно."""
    now = time.time()
    with _fails_lock:
        stamps = _recent(ip, now)
        if len(stamps) < FAIL_LIMIT:
            return 0
        return max(1, int(FAIL_WINDOW - (now - stamps[0])))


def note_fail(ip: str) -> None:
    now = time.time()
    with _fails_lock:
        _recent(ip, now)
        _fails.setdefault(ip, []).append(now)


def note_ok(ip: str) -> None:
    with _fails_lock:
        _fails.pop(ip, None)
