"""Freeze local API ingress before checking whether restart is safe.

This gate never cancels user work and performs no remote requests. A rejected
restart reopens ingress; a successful handoff leaves it frozen until process exit.
"""
from functools import wraps
import json
from pathlib import Path
import sys
import threading
import time

_condition = threading.Condition()
_frozen = False
_active = 0


class UpdateBusy(RuntimeError):
    pass


def request_handler(function):
    @wraps(function)
    def guarded(handler, *args, **kwargs):
        global _active
        with _condition:
            if _frozen:
                handler._json({'error': 'Приложение готовится к обновлению. Повторите запрос после перезапуска.'}, 503)
                return
            _active += 1
        try:
            return function(handler, *args, **kwargs)
        finally:
            with _condition:
                _active -= 1
                _condition.notify_all()
    return guarded


def unfreeze():
    global _frozen
    with _condition:
        _frozen = False
        _condition.notify_all()


def freeze(timeout=35):
    global _frozen
    deadline = time.monotonic() + timeout
    with _condition:
        if _frozen:
            raise UpdateBusy('Обновление уже подготавливает перезапуск')
        _frozen = True
        while _active:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _frozen = False
                raise UpdateBusy('Дождитесь завершения текущих запросов и повторите обновление')
            _condition.wait(remaining)


def assert_idle(root):
    """Called only with ingress frozen and proxy maintenance acknowledged as parked.

    All application-owned Thread targets in this client were inventoried. Unknown
    application threads and unresolved on-disk intents fail closed.
    """
    with _condition:
        if not _frozen or _active:
            raise UpdateBusy('Не удалось приостановить входящие запросы')
    current = threading.current_thread()
    for worker in threading.enumerate():
        if worker is current or worker is threading.main_thread():
            continue
        target = getattr(worker, '_target', None)
        module = getattr(target, '__module__', '')
        owner = type(worker).__module__
        pool = sys.modules.get('modules.proxy_pool')
        if pool is not None and pool.maintenance_quiescent(worker):
            continue
        if module in ('main', '__main__') or module.startswith('modules.') or owner.startswith('modules.'):
            raise UpdateBusy('Дождитесь завершения публикации, входа, регистрации или фоновой проверки')
    server = sys.modules.get('main')
    if server is not None and getattr(server, '_studio_busy', False):
        raise UpdateBusy('Дождитесь завершения обновления студии')
    root = Path(root)
    pending = root / 'sessions' / 'browser-jobs'
    if pending.is_symlink():
        raise UpdateBusy('Не удалось проверить незавершённые браузерные задания')
    if pending.exists() and any(p.is_file() or p.is_symlink() for p in pending.rglob('*')):
        raise UpdateBusy('Сначала проверьте результат незавершённой браузерной операции')
    registration = root / 'registration'
    if registration.is_symlink():
        raise UpdateBusy('Не удалось проверить незавершённые регистрации')
    if registration.exists():
        for file in registration.glob('*.json'):
            try:
                if file.is_symlink():
                    raise ValueError('linked registration record')
                row = json.loads(file.read_text(encoding='utf-8'))
                phase = row.get('status')
                complete = phase == 'complete' and row.get('account_saved') is True
                terminal = phase in ('failed', 'cancelled') and row.get('server_reason') != 'browser_cleanup_unconfirmed'
                if not (complete or terminal):
                    raise UpdateBusy('Сначала проверьте результат незавершённой регистрации')
            except (OSError, ValueError, AttributeError) as error:
                raise UpdateBusy('Не удалось безопасно проверить журнал регистрации') from error
    edits = root / 'profile-edits'
    if edits.is_symlink():
        raise UpdateBusy('Не удалось проверить незавершённые изменения профиля')
    if edits.exists():
        from .profile_edit import _requires_readback

        for file in edits.glob('*.json'):
            try:
                if file.is_symlink():
                    raise ValueError('linked profile record')
                row = json.loads(file.read_text(encoding='utf-8'))
                if row.get('reconciled') is not True and _requires_readback(row):
                    raise UpdateBusy('Сначала перечитайте профиль с неподтверждённым изменением')
            except (OSError, ValueError, AttributeError, TypeError) as error:
                raise UpdateBusy('Не удалось безопасно проверить журнал изменений профиля') from error
