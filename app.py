# -*- coding: utf-8 -*-
"""Точка входа для пользователей: сервер + нативное окно (pywebview).

Никакой ссылки открывать не надо — сразу открывается окно приложения.
Сервер (main.py) поднимается в фоновом потоке и привязывается СТРОГО к
127.0.0.1 — API не должен быть доступен с других устройств сети (аудит:
host из config.json больше не используется в нативном запуске). При
закрытии окна сервер останавливается.

Занятый порт не роняет приложение: пробуем port, port+1, … port+20 из
config.json (или аргумента); все заняты — нативный messagebox с понятным
сообщением и выход. Окно открывается на фактически выбранный порт.

Разработчику для CLI-прогонов без окна — python main.py [порт] [host]."""
import ctypes
import json
import os
import re
import shutil
import socket
import sys
import threading
import time
import traceback
import webbrowser
from datetime import datetime
from pathlib import Path

# Retain this object until actual process termination, including worker threads.
_BOOTSTRAP_GUARD = None


def _early_bootstrap():
    global _BOOTSTRAP_GUARD
    packaged = bool(getattr(sys, "frozen", False) or "__compiled__" in globals())
    if not packaged:
        return
    from modules import bootstrap
    executable = Path(sys.executable).absolute()
    if len(sys.argv) > 1 and sys.argv[1] == "--activate-runtime":
        if len(sys.argv) != 7:
            raise bootstrap.BootstrapError("Invalid activation arguments")
        root, staged, version, expected_digest = sys.argv[2:6]
        if not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
            raise bootstrap.BootstrapError("Invalid verified inventory digest")
        readiness = Path(sys.argv[6]).absolute()
        ready_sent = False
        if readiness is not None and (
                readiness.parent != Path(staged).absolute().parent
                or not re.fullmatch(r"\.nimbus-activation-ready-[0-9a-f]{32}", readiness.name)):
            raise bootstrap.BootstrapError("Invalid activation readiness path")
        def ready():
            nonlocal ready_sent
            if readiness is not None:
                descriptor = os.open(readiness, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "w", encoding="ascii") as stream:
                    stream.write("ready\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                ready_sent = True
        # Run the helper from the intact CURRENT runtime. Never run it from the
        # staged directory that must be renamed (Windows holds executable files).
        if executable != bootstrap.selected_runtime(root) / bootstrap.executable_name():
            raise bootstrap.BootstrapError("Activation helper is not the current runtime")
        try:
            bootstrap.activate(root, staged, version, ready=ready, expected_digest=expected_digest)
        except Exception:
            if ready_sent:
                try:
                    bootstrap.relaunch_current_if_idle(root)
                except Exception:
                    pass  # Never execute code when the selected runtime is invalid.
            raise
        try:
            bootstrap.cleanup_staging(root, staged, version)
        except (OSError, bootstrap.BootstrapError):
            pass  # A leftover public package must never prevent application restart.
        bootstrap.launch(root)
        raise SystemExit(0)
    if (executable.name == bootstrap.executable_name()
            or (executable.parent / bootstrap.RUNTIME_MARKER).exists()):
        _BOOTSTRAP_GUARD = bootstrap.enter_runtime(executable)


if __name__ == "__main__":
    try:
        _early_bootstrap()
    except Exception as _bootstrap_error:
        # This path deliberately runs before webview, config or user-data imports.
        if sys.platform == "win32":
            ctypes.windll.user32.MessageBoxW(0, str(_bootstrap_error), "Nimbus", 0x10)
        elif sys.stderr is not None:
            print(str(_bootstrap_error), file=sys.stderr)
        raise SystemExit(1)


def _configure_linux_webview(env, platform: str) -> None:
    """Use the verified GTK/WebKit path when a desktop offers X11 and Wayland."""
    if (platform != "linux" or not env.get("DISPLAY") or not env.get("WAYLAND_DISPLAY")
            or env.get("GDK_BACKEND", "") not in ("", "wayland,x11,*")):
        return
    env["GDK_BACKEND"] = "x11"
    env.setdefault("WEBKIT_DISABLE_COMPOSITING_MODE", "1")
    env.setdefault("WEBKIT_DISABLE_DMABUF_RENDERER", "1")


_configure_linux_webview(os.environ, sys.platform)

import webview

from modules.brand import PRODUCT
from modules.console import configure_console

configure_console()

# сколько запасных портов перебираем, если занятый
_PORT_TRIES = 20

# что копится у пользователя рядом с exe и едет в новую версию: копией
# (прошлая версия остаётся рабочей) или переносом — креативы бывают на
# гигабайты, копировать их долго, а на том же диске перенос мгновенный
_CARRY_COPY = ("config.json", "accounts.json", "banned.json", "data.db",
               "data.db-wal", "data.db-shm", "tiktok_cookies.json", "sessions",
               "registration", "profile-edits", "browser_states", "proxies.txt")
_CARRY_MOVE = ("media", "assets")

NL = chr(10)


def _app_dir() -> Path:
    """Папка приложения: рядом с exe (собранное) или корень проекта (dev)."""
    if _BOOTSTRAP_GUARD is not None:
        return Path(os.environ["NIMBUS_BOOTSTRAP_ROOT"])
    if getattr(sys, "frozen", False) or "__compiled__" in globals():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _version_of(folder: Path, name: str):
    """(1, 1, 0) из «<name> v1.1.0»; чужая папка — None."""
    m = re.fullmatch(re.escape(name) + r" v(\d+(?:\.\d+)*)", folder.name)
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def _carry_over(here: Path) -> None:
    """Новая версия распаковывается рядом с прошлой («… v1.1.1» возле
    «… v1.1.0»). При первом запуске забираем оттуда настройки, аккаунты,
    входы и креативы — иначе программа открылась бы пустой."""
    if any((here / item).exists() for item in _CARRY_COPY):
        return
    name, _, _ = here.name.rpartition(" v")
    mine = _version_of(here, name) if name else None
    if mine is None:
        return
    older = [(v, d) for d in here.parent.iterdir()
             if d.is_dir() and (v := _version_of(d, name)) is not None and v < mine
             and any((d / item).exists() for item in _CARRY_COPY)]
    if not older and name == "Nimbus":
        older = [(v, d) for d in here.parent.iterdir()
                 if d.is_dir() and (v := _version_of(d, "TikTok Web API")) is not None
                 and any((d / item).exists() for item in _CARRY_COPY)]
    if not older:
        return
    _, prev = max(older)
    for item in _CARRY_COPY + _CARRY_MOVE:
        src, dst = prev / item, here / item
        if not src.exists() or dst.exists():
            continue
        try:
            if src.is_dir():
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
        except OSError as exc:
            _log(f"перенос {item} из «{prev.name}» не удался: {exc!r}")
    _log(f"данные перенесены из «{prev.name}»")


def _log(text: str) -> None:
    """Пишет в logs/app.log рядом с приложением. Единственный способ понять,
    почему exe не открылся: консоли у собранного приложения нет, а окно
    как раз и могло не подняться."""
    try:
        d = _app_dir() / "logs"
        d.mkdir(exist_ok=True)
        with open(d / "app.log", "a", encoding="utf-8") as f:
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(stamp + " " + text + chr(10))
    except Exception:
        pass
    print(text, file=sys.stderr)


def _msgbox(text: str, title: str = PRODUCT) -> bool:
    """Показать блокирующий диалог; False, если окно недоступно."""
    try:
        if sys.platform == "win32":
            return bool(ctypes.windll.user32.MessageBoxW(
                0, text, title, 0x40))  # MB_ICONINFORMATION
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk
        ready, _ = Gtk.init_check()
        if not ready:
            return False
        dialog = Gtk.MessageDialog(
            modal=True, message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK, text=title)
        try:
            dialog.format_secondary_text(text)
            dialog.run()
        finally:
            dialog.destroy()
        return True
    except Exception as exc:
        _log("не удалось показать сообщение: " + repr(exc))
        return False


def _wait_for_completion(text: str) -> None:
    """Без окна ждём Enter в терминале или Ctrl+C, сохраняя сервер живым."""
    if _msgbox(text):
        return
    print(text, file=sys.stderr)
    try:
        if sys.stdin is not None and sys.stdin.isatty():
            input("Нажмите Enter, чтобы завершить работу: ")
            return
    except (EOFError, OSError, ValueError):
        pass
    print("Для завершения работы нажмите Ctrl+C.", file=sys.stderr)
    stop = threading.Event()
    while True:
        stop.wait(1)


def _webview2_missing() -> bool:
    """Нет ли WebView2 Runtime — движка, которым pywebview рисует окно.
    На Win11 он есть всегда, на Win10 без обновлений может отсутствовать,
    и тогда окно не откроется (в логах — падение winforms/mshtml)."""
    if sys.platform != "win32":
        return False
    try:
        from webview.platforms import winforms
        return not winforms.is_chromium
    except Exception:
        return True


def _port_free(port: int, host: str = "127.0.0.1") -> bool:
    """Занят ли порт. Отдельная проба сокетом нужна потому, что
    ThreadingHTTPServer на Windows ставит SO_REUSEADDR и МОЖЕТ забиндиться
    поверх уже слушающего сокета (без OSError) — два сервера на одном порту,
    трафик уходит старому, окно показывает пустую страницу. Обычный сокет
    без SO_REUSEADDR честно отказывается биндиться на занятый порт."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if sys.platform != "win32":
            # Linux permits a listener to reuse its closed connections without
            # allowing another listener to share a currently occupied address.
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


class Api:
    """Системные файловые диалоги, доступные фронту через window.pywebview.api.

    Работают только внутри нативного окна pywebview (app.py) — при запуске
    main.py напрямую и открытии в обычном браузере window.pywebview
    отсутствует, доступность методов фронт должен определять по нему сам."""

    def __init__(self):
        self._updates = None
        self._updates_lock = threading.Lock()
        self._restart_lock = threading.Lock()
        self._restart_requested = False

    def _client_updater(self):
        with self._updates_lock:
            if self._updates is None:
                from modules import changelog, client_updates
                self._updates = client_updates.Updater(_app_dir(), changelog.load()["version"],
                    packaged=bool(getattr(sys, "frozen", False) or "__compiled__" in globals()),
                    guarded=_BOOTSTRAP_GUARD is not None, executable=sys.executable)
            return self._updates

    def check_client_update(self):
        from modules.client_updates import UpdateError
        try:
            return self._client_updater().check()
        except UpdateError as exc:
            return {"error": str(exc)}
        except Exception:
            return {"error": "Не удалось проверить обновления. Текущая версия сохранена."}

    def prepare_client_update(self):
        from modules.client_updates import UpdateError
        try:
            return self._client_updater().prepare()
        except UpdateError as exc:
            return {"error": str(exc)}
        except Exception:
            return {"error": "Не удалось подготовить обновление. Текущая версия и данные сохранены."}

    def restart_client_update(self):
        from modules import bootstrap, proxy_pool, update_activity
        from modules.client_updates import UpdateError
        import secrets
        import subprocess

        def cancel_helper(helper):
            if helper is None or helper.poll() is not None:
                return
            try:
                helper.terminate()
                helper.wait(timeout=5)
            except ProcessLookupError:
                helper.wait(timeout=5)
            except subprocess.TimeoutExpired:
                helper.kill()
                helper.wait(timeout=5)

        if not self._restart_lock.acquire(blocking=False):
            return {"error": "Перезапуск уже подготавливается"}
        frozen = False
        paused = False
        launched = None
        readiness = None
        try:
            if self._restart_requested:
                return {"error": "Перезапуск уже запрошен"}
            if _BOOTSTRAP_GUARD is None or not getattr(webview, "windows", None):
                raise UpdateError("Для этой установки требуется ручной переход на bootstrap-версию")
            updater = self._client_updater()
            updater._exclusive()
            try:
                root, staged, version = updater.activation_arguments()
                expected_digest = updater.activation_digest()
                update_activity.freeze()
                frozen = True
                paused = True
                if not proxy_pool.pause_for_update():
                    raise update_activity.UpdateBusy("Дождитесь завершения фоновой проверки прокси")
                update_activity.assert_idle(root)
                readiness = Path(staged).parent / (".nimbus-activation-ready-" + secrets.token_hex(16))
                command = [sys.executable, "--activate-runtime", root, staged, version, expected_digest, str(readiness)]
                options = {"cwd": root, "close_fds": True, "stdin": subprocess.DEVNULL,
                           "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
                if sys.platform != "win32":
                    options["start_new_session"] = True
                launched = subprocess.Popen(command, **options)
                deadline = time.monotonic() + 15
                while True:
                    if launched.poll() is not None:
                        raise UpdateError("Помощник обновления не запустился. Приложение остаётся открытым.")
                    if readiness.is_symlink():
                        raise UpdateError("Не удалось подтвердить готовность обновления")
                    if readiness.exists():
                        signal = readiness.read_bytes()
                        if signal == b"ready\n":
                            break
                        if signal:
                            raise UpdateError("Не удалось подтвердить готовность обновления")
                    if time.monotonic() >= deadline:
                        raise UpdateError("Помощник обновления не подтвердил готовность. Повторите позже.")
                    time.sleep(.05)
                if launched.poll() is not None:
                    raise UpdateError("Не удалось подтвердить готовность обновления")
                readiness.unlink()
                self._restart_requested = True
                helper = launched
                # Deliver the bridge response before orderly window/server shutdown.
                def close_window():
                    try:
                        webview.windows[0].destroy()
                    except Exception:
                        try:
                            cancel_helper(helper)
                        except (OSError, subprocess.TimeoutExpired):
                            return
                        self._restart_requested = False
                        proxy_pool.resume_after_update()
                        update_activity.unfreeze()
                timer = threading.Timer(.2, close_window)
                timer.daemon = True
                try:
                    timer.start()
                except Exception:
                    self._restart_requested = False
                    raise
                launched = None  # The waiting helper owns the handoff now.
                frozen = paused = False  # Stay frozen/parked until actual process exit.
                return {"ok": True}
            finally:
                updater.lock.release()
        except (UpdateError, update_activity.UpdateBusy, bootstrap.BootstrapError) as error:
            return {"error": str(error)}
        except Exception:
            return {"error": "Обновление не запущено. Приложение и данные сохранены."}
        finally:
            try:
                cancel_helper(launched)
            except (OSError, subprocess.TimeoutExpired):
                pass
            if readiness is not None and readiness.is_file() and not readiness.is_symlink():
                try:
                    readiness.unlink(missing_ok=True)
                except OSError:
                    pass
            if paused:
                proxy_pool.resume_after_update()
            if frozen:
                update_activity.unfreeze()
            self._restart_lock.release()

    def open_client_update(self):
        try:
            staged = self._client_updater().staged
            if not staged:
                return {"error": "Сначала скачайте и проверьте обновление"}
            folder = str(staged[0])
            if sys.platform == "win32":
                os.startfile(folder)
            else:
                import subprocess
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", folder],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
            return {"ok": True}
        except Exception:
            return {"error": "Не удалось открыть папку обновления"}

    def pick_folder(self):
        """Открывает системный диалог выбора одной папки. Возвращает путь
        строкой, либо None, если пользователь отменил."""
        result = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER)
        return result[0] if result else None

    def pick_files(self, allow_multiple=True):
        """Открывает системный диалог выбора файла(ов) — по умолчанию можно
        выбрать несколько сразу. Фильтр на фото-форматы (плюс все файлы).
        Возвращает список путей строками (пустой список, если отменено)."""
        from modules.photo_source import PHOTO_EXTS
        masks = ";".join("*" + ext for ext in sorted(PHOTO_EXTS))
        file_types = ("Изображения (%s)" % masks, "Все файлы (*.*)")
        result = webview.windows[0].create_file_dialog(
            webview.FileDialog.OPEN, allow_multiple=allow_multiple, file_types=file_types)
        return list(result) if result else []


def _fatal_messagebox(text: str) -> None:
    """Записать ошибку и показать её без участия pywebview."""
    _log("ФАТАЛЬНО: " + text)
    _msgbox(text, f"{PRODUCT} — ошибка запуска")


def _browser_fallback(url: str, text: str) -> None:
    """Открыть браузер и дождаться явного завершения пользователем.
    Сервером владеет main: он закрывает его при любом выходе."""
    try:
        opened = webbrowser.open(url)
    except Exception as exc:
        message = "Не удалось открыть браузер: " + str(exc)
        _fatal_messagebox(message)
        raise RuntimeError(message) from exc
    if not opened:
        message = "Не удалось открыть браузер. Адрес интерфейса: " + url
        _fatal_messagebox(message)
        raise RuntimeError(message)
    _wait_for_completion(text + NL + NL + "Адрес: " + url + NL
                         + "Не закрывайте это сообщение, пока работаете.")


def _check_ui(window, report: Path) -> None:
    """Explicit build-check mode: verify real DOM in the selected native webview."""
    result = {"ok": False, "routes": []}
    try:
        if not window.events.loaded.wait(60):
            raise RuntimeError("Native document did not load")
        window.evaluate_js("window.__nativeCheckErrors=[]; addEventListener('error',e=>__nativeCheckErrors.push(e.message)); true")
        routes = (("/", "Публикация"), ("/accounts", "Аккаунты"), ("/proxies", "Прокси"),
                  ("/media", "Креативы"), ("/logs", "Логи"), ("/settings", "Настройки"),
                  ("/profile", "Профиль"))
        for route, heading in routes:
            window.evaluate_js("location.hash=" + json.dumps(route) + "; true")
            state = None
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                state = window.evaluate_js("(()=>{const h=[...document.querySelectorAll('h1')].find(e=>e.textContent.trim()===" + json.dumps(heading) + "); return {heading:h?.textContent,ready:!!h&&h.getBoundingClientRect().width>0,overflow:document.documentElement.scrollWidth>innerWidth+1,errors:window.__nativeCheckErrors};})()")
                if isinstance(state, dict) and state.get("ready"):
                    break
                time.sleep(.1)
            if not isinstance(state, dict) or not state.get("ready"):
                raise RuntimeError("Native route did not render: " + route)
            if state.get("overflow") or state.get("errors"):
                raise RuntimeError("Native page failed its layout check")
            result["routes"].append({"route": route, **state})
        time.sleep(.5)
        result["ok"] = True
    except Exception as exc:
        result["error"] = str(exc)
    finally:
        report.write_text(json.dumps(result), encoding="utf-8")
        # Give the external acceptance harness time to capture the rendered
        # window after the report has been flushed.
        if result.get("ok"):
            time.sleep(5)
        window.destroy()


def main() -> int:
    # до импорта сервера: он заводит config.json с настройками по умолчанию,
    # и перенос решил бы, что папка уже обжита
    if _BOOTSTRAP_GUARD is None:
        _carry_over(_app_dir())
    import main as server_mod

    port = int(sys.argv[1]) if len(sys.argv) > 1 else None
    base_port = port if port is not None else int(
        server_mod.config.get("port") or 8740)

    # По умолчанию слушаем только этот компьютер (аудит: не светить API
    # наружу). С доступом с телефона — всю сеть, но с чужих адресов только по
    # паролю; без пароля доступ не включается, даже если его вписали в
    # config.json руками. port..port+20: доступность проверяем пробой сокета
    # (см. _port_free) — build_server с SO_REUSEADDR на Windows занятость не ловит.
    from modules import auth
    phone = bool(server_mod.config.get("phone_access")) and auth.enabled()
    host = "127.0.0.1"
    httpd = None
    for offset in range(_PORT_TRIES):
        if not _port_free(base_port + offset, host):
            continue
        try:
            httpd = server_mod.build_server(base_port + offset, host, auth=True)
            if phone:
                httpd.set_phone_access(True)
            break
        except OSError:
            if httpd is not None:
                httpd.server_close()
                httpd = None
            continue
    if httpd is None:
        _fatal_messagebox(
            f"Не удалось запустить локальный сервер: порты "
            f"{base_port}–{base_port + _PORT_TRIES - 1} заняты. "
            f"Закройте другие копии приложения (или освободите порт) "
            f"и попробуйте снова.")
        return 1

    _, actual_port = httpd.server_address
    url = f"http://127.0.0.1:{actual_port}"
    if actual_port != base_port:
        print(f"[app] порт {base_port} занят — сервер на {actual_port}", file=sys.stderr)

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    try:
        _log("сервер поднят на " + url)

        # Окно рисует WebView2 (Edge Chromium). На Win11 он есть всегда, на
        # Win10 без обновлений может отсутствовать — тогда окно не открыть.
        # Молча падать нельзя (консоли нет), поэтому: понятное сообщение +
        # запасной путь — тот же интерфейс в браузере по умолчанию.
        if _webview2_missing():
            _log("WebView2 не найден — запасной путь через браузер")
            _browser_fallback(url,
                              "Для окна программы нужен компонент Microsoft Edge "
                              "WebView2, на этом компьютере его нет." + NL + NL +
                              "Интерфейс открыт в браузере — работайте в нём." + NL + NL +
                              "Чтобы открывалось своим окном, установите бесплатный "
                              "Microsoft Edge WebView2 Runtime с сайта Microsoft "
                              "и запустите программу заново.")
            return 0

        # 1280×900 — десктопная раскладка с развёрнутым меню (web/, меню сворачивается
        # само уже 1024px); min_size всё равно пускает в узкую раскладку, если
        # пользователь сузит окно вручную.
        # background_color — цвет фона интерфейса: без него окно на долю секунды
        # вспыхивает белым, пока грузится страница.
        # text_select=True: по умолчанию pywebview запрещает выделять текст во всём
        # окне — не скопировать ни строку лога, ни логин. Где выделение мешает
        # (кнопки, строки списков), интерфейс запрещает его сам.
        try:
            window = webview.create_window(PRODUCT, url, width=1280, height=900,
                                  min_size=(760, 560), js_api=Api(),
                                  background_color="#0a0a0a", text_select=True)
            # private_mode=False: localStorage окна живёт между запусками. С дефолтным
            # приватным профилем каждый старт exe забывал активную вкладку, тумблер
            # «Подробно» и прочие UI-настройки (тексты формы публикации теперь и так
            # хранятся в config.json, но интерфейсные мелочи — только здесь). Профиль
            # WebView2 кладётся в %APPDATA%\pywebview
            check_report = None
            if "--check-ui" in sys.argv:
                index = sys.argv.index("--check-ui")
                check_report = Path(sys.argv[index + 1]).resolve()
            if check_report is not None:
                webview.start(lambda: _check_ui(window, check_report), private_mode=False)
            else:
                webview.start(private_mode=False)
        except Exception as exc:
            _log("окно не открылось: " + repr(exc) + NL + traceback.format_exc())
            _browser_fallback(url,
                              "Не удалось открыть окно программы на этом компьютере." + NL + NL +
                              "Интерфейс открыт в браузере — работайте в нём." + NL + NL +
                              "Подробности записаны в файл logs" + chr(92) + "app.log "
                              "рядом с программой.")
            return 0
    finally:
        try:
            httpd.shutdown()
        finally:
            httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
