"""Client login orchestration through the Nimbus service."""

import sys
import threading
import time
from pathlib import Path

from . import eventlog, proxy_pool
from .accounts import load_account

BASE = Path(__file__).resolve().parent.parent
LOG_DIR = BASE / "logs"
LOG_FILE = LOG_DIR / "pure_login.log"

# причина последней неудачи run() — для внешнего API (main.py._api_login) и
# кампании: человеческий текст, без секретов. run() сбрасывает перед каждой
# попыткой, читается через last_reason(). Своя на поток: входы идут
# параллельно (воркеры кампании, «Войти во все»), и общая переменная отдала
# бы одному аккаунту причину соседнего.
_reason_tls = threading.local()

# Коды error_code от passport, при которых вход не выйдет и держать аккаунт
# в списке рабочих незачем: кампания и ручной вход уносят его в banned.json
# (см. last_banned()). Коды только с однозначным смыслом — расширять проверенным:
#   1011 — «Account doesn't exist»: удалён или забанен (проверено живьём);
#   1091 — «Account is currently suspended»: приостановлен, пароль и 2FA приняты,
#          отказ после них (2026-09-16). Временной зовёт TikTok — срока нет:
#          вернуть может только человек. Сеть, капча, пароль сюда НЕ входят.
# Код проверяется на каждом шаге, где TikTok может отказать: пароль, код 2FA,
# отправка и проверка кода из почты, финальный вход. Живьём 1091 видели только
# после 2FA, на остальных шагах признак стоит по тому же смыслу кода.
BANNED_CODES = {1011, 1091}
# Отключённому по этим кодам сессию не сносим: приостановку TikTok может снять, и
# «Вернуть» отдаст аккаунт вместе с ещё живой сессией, а не только с паролем.
# Аккаунта, которого больше нет (1011), это не касается — там сессия мертва.
KEEP_SESSION_CODES = {1091}

class _Tee:
    """stdout -> терминал + logs/pure_login.log (по строчкам, с меткой времени)."""

    def __init__(self):
        LOG_DIR.mkdir(exist_ok=True)
        self._f = open(LOG_FILE, "a", encoding="utf-8", newline="")

    def write(self, text):
        import sys
        sys.__stdout__.write(text)
        self._f.write(text)
        self._f.flush()

    def flush(self):
        import sys
        sys.__stdout__.flush()
        self._f.flush()


def last_reason() -> str:
    """Причина последней неудачи run() в ЭТОМ потоке человеческим текстом,
    пусто — если попытки ещё не было или причина не распозналась."""
    return getattr(_reason_tls, "text", "")


def last_network() -> bool:
    """Последний вход сорвался на сети; это диагностика, не разрешение повтора.

    После отправки запроса сервер мог уже выполнить защищённые шаги входа."""
    return getattr(_reason_tls, "network", False)


def last_banned() -> bool:
    """Последний вход в этом потоке отказал по коду из BANNED_CODES (1011,
    приостановка 1091): аккаунт сам не оживёт, кампания убирает его из списка."""
    return last_ban_code() is not None


def last_ban_code():
    """Код из BANNED_CODES, которым отказал последний вход в этом потоке; None —
    отказ был не баном. По нему отключение решает, сносить ли сессию
    (KEEP_SESSION_CODES)."""
    return getattr(_reason_tls, "ban_code", None)


def _set_reason(text: str, network: bool = False, banned=None) -> None:
    """banned — код из BANNED_CODES (см. _ban_code), None — не бан."""
    _reason_tls.text = text or ""
    _reason_tls.network = network
    _reason_tls.ban_code = banned or None


def attempt_via_server(acc, proxy, account_name) -> bool:
    """То же, что attempt, но входит наш сервер (modules/cloud.py): причина,
    сбой сети и бан — в тех же last_reason/last_network/last_ban_code."""
    from . import client_session, cloud, remote
    _set_reason("")
    try:
        # Persist the account route before handing off any login step. Keep
        # reporting pool health against the original configured gateway.
        via = client_session.sticky_proxy(proxy, acc.get("username"))
    except (OSError, ValueError):
        _set_reason("не удалось сохранить параметры прокси аккаунта — проверьте его локальные данные")
        return False
    try:
        if not acc.get('password'):
            checked = cloud.session_check(acc['username'], via)
            owner = str(checked.get('username') or '').lstrip('@')
            ok = checked.get('alive') is True and owner.casefold() == acc['username'].casefold()
            out = {'ok': ok, 'network': checked.get('network', False),
                   'reason': '' if ok else 'Сессия по куки не подтверждена. Нужны действующие куки или пароль.'}
        else:
            out = cloud.login(acc, via)
    except remote.RemoteError as exc:
        print(f"[login] {account_name}: сервер: {exc}")
        _set_reason(str(exc), exc.network)
        return False
    network = bool(out.get("network"))
    if network:
        proxy_pool.report_fail(proxy, out.get("reason") or "сбой сети")
    else:
        proxy_pool.report_ok(proxy)
    ban = out.get("ban_code") if out.get("banned") else None
    _set_reason(out.get("reason") or "", network, ban if ban in BANNED_CODES else None)
    return bool(out.get("ok"))


def run(name=None, tee=True, proxy=None) -> bool:
    """Вход аккаунтом `name` (None — по умолчанию из config). Возвращает успех.

    proxy — прокси этого входа (воркер кампании передаёт свой; None — ручной
    вход из UI: прокси арендуется у proxy_pool, наименее занятый живой, и
    параллельные входы «Войти во все» расходятся по разным прокси).

    Итог уходит в ленту событий одной строкой: «вход выполнен» или «вход не
    удался: причина». Шаги, коды TikTok и заголовки — в подробности.

    Сбой сети или прокси отмечается в last_network() и уходит в proxy_pool;
    ответ TikTok, даже отказ, значит, что прокси довёз запрос. Один вызов
    отправляет один вход: неизвестный исход не разрешает повторить пароль
    на другом прокси. Неотправленные запросы различает сам remote._send."""
    _set_reason("")
    acc = load_account(name)
    account_name = acc.get("username")
    if tee:
        sys.stdout = _Tee()
    print(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} аккаунт {account_name} =====")
    held = None
    ok = False
    try:
        if proxy is None:
            # ручной вход: прокси выбираем сами и, если у него есть ссылка смены
            # IP, дёргаем её перед входом — как кампания перед каждым аккаунтом
            from . import proxies as proxies_mod
            held = proxy_pool.lease(task="login")
            proxy = held.url
            if proxy:
                proxies_mod.rotate_for(proxy, log=eventlog.teller(account_name, "proxy"))
        ok = attempt_via_server(acc, proxy, account_name)
    except proxy_pool.NoAliveProxy as exc:
        _set_reason(str(exc))
    finally:
        if held is not None:
            held.release()
    if ok:
        eventlog.say("вход выполнен", "ok", account_name, "login")
    else:
        eventlog.say("вход не удался: %s" % (last_reason() or "причина неизвестна"),
                     "err", account_name, "login")
    return ok
