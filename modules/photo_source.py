"""Media folders, processing and client upload preparation."""

import io
import os
import re
import shutil
import threading
from pathlib import Path

from PIL import Image, ImageOps

from . import uniq
from .tos_transfer import TOSUploadError
from .media_info import VIDEO_EXTS

PHOTO_EXTS = uniq.PHOTO_EXTS

# что публикуем: фото (карусель из папок-слотов) или видео (один ролик на пост)
MEDIA = ("photo", "video")
MEDIA_EXTS = {"photo": PHOTO_EXTS, "video": VIDEO_EXTS}
# слово для сообщений пользователю: «фото» / «видео» (оба не склоняются)
MEDIA_WORD = {"photo": "фото", "video": "видео"}


# --- папки программы -------------------------------------------------------
#
# Папки, которые программа держит сама — media/<имя> рядом с ней. Нужны тем,
# кто работает по ссылке (телефон, айфон): выбрать папку на чужом диске или
# вписать к ней путь там нечем, а загрузить файлы из галереи в папку по имени
# — можно. Файлы пишутся сразу на диск (_api_slots_upload): закрыл страницу —
# загруженное осталось. В форме публикации такая папка — обычный путь, только
# абсолютный: рабочую папку программа не задаёт, и относительный путь зависел
# бы от того, откуда её запустили.

LIBRARY_DIR = "media"
# в имени — ни путей, ни символов, которые Windows в имени не пускает
_BAD_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
NAME_MAX = 60


def library_root() -> Path:
    return Path(__file__).resolve().parent.parent / LIBRARY_DIR


# сколько свежих фото папки отдавать обложкой её карточки в «Креативах»
PREVIEW_COUNT = 4


def _library_entry(folder: Path) -> dict:
    photos, videos = [], 0
    for f in folder.iterdir():
        if not f.is_file() or f.name.endswith((".part", ".claim_")):
            continue
        ext = f.suffix.lower()
        if ext in PHOTO_EXTS:
            photos.append((int(f.stat().st_mtime), f.name))
        videos += ext in VIDEO_EXTS
    photos.sort(reverse=True)
    return {"name": folder.name, "path": str(folder), "photos": len(photos), "videos": videos,
            "mtime": int(folder.stat().st_mtime),
            "preview": [{"file": n, "mtime": m} for m, n in photos[:PREVIEW_COUNT]]}


def library() -> dict:
    """Папки программы, свежие сверху: {root, folders: [{name, path, photos,
    videos, mtime}]}. Корня ещё нет — пустой список."""
    root = library_root()
    folders = []
    if root.is_dir():
        folders = [_library_entry(p) for p in root.iterdir() if p.is_dir()]
    folders.sort(key=lambda f: f["mtime"], reverse=True)
    return {"root": str(root), "folders": folders}


def _library_folder(name: str) -> Path:
    """Папка программы по имени; ValueError — имя пустое или с путём."""
    name = (name or "").strip()
    if not name or name in (".", "..") or _BAD_NAME.search(name):
        raise ValueError("имя папки — без / \\ : * ? \" < > |")
    if len(name) > NAME_MAX:
        raise ValueError(f"имя папки — не длиннее {NAME_MAX} знаков")
    return library_root() / name


def library_create(name: str = "", default: str = "") -> dict:
    """Новая папка программы. Пустое имя — default (форма даёт «Галерея
    25.09 14:32»); занято — к имени добавляется номер."""
    base = (name or "").strip() or (default or "").strip() or "Папка"
    folder = _library_folder(base)
    for n in range(2, 1000):
        if not folder.exists():
            break
        folder = _library_folder(f"{base} ({n})")
    folder.mkdir(parents=True)
    return _library_entry(folder)


def library_clear(name: str) -> int:
    """Удалить из папки программы все фото и видео; сколько удалено."""
    folder = _library_folder(name)
    if not folder.is_dir():
        raise ValueError(f"папки «{name}» нет")
    removed = 0
    for f in folder.iterdir():
        if f.is_file():
            f.unlink()
            removed += 1
    return removed


def _library_file(name: str, file: str) -> Path:
    """Файл папки программы; ValueError — имя с путём или файла нет."""
    folder = _library_folder(name)
    if not file or Path(file).name != file or file in (".", ".."):
        raise ValueError("неверное имя файла")
    path = folder / file
    if not path.is_file():
        raise ValueError(f"файла «{file}» нет")
    return path


def library_files(name: str) -> list:
    """Фото и видео папки программы, свежие сверху: [{file, kind, size,
    mtime}]. Недокачанные (.part) и взятые публикацией (.claim_) не
    показываются."""
    folder = _library_folder(name)
    if not folder.is_dir():
        raise ValueError(f"папки «{name}» нет")
    out = []
    for f in folder.iterdir():
        ext = f.suffix.lower()
        kind = "photo" if ext in PHOTO_EXTS else "video" if ext in VIDEO_EXTS else None
        if kind and f.is_file():
            st = f.stat()
            out.append({"file": f.name, "kind": kind, "size": st.st_size,
                        "mtime": int(st.st_mtime)})
    out.sort(key=lambda it: it["mtime"], reverse=True)
    return out


THUMB_SIZE = 320


def library_thumb(name: str, file: str, size: int = THUMB_SIZE) -> bytes:
    """Превью фото из папки программы — JPEG по длинной стороне size, с
    учётом поворота из EXIF (снимки с айфона иначе лягут боком). Видео —
    ValueError: кадр из ролика без декодера не достать."""
    path = _library_file(name, file)
    if path.suffix.lower() not in PHOTO_EXTS:
        raise ValueError("превью есть только у фото")
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        im.thumbnail((size, size))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=80)
    return buf.getvalue()


def library_remove_file(name: str, file: str) -> None:
    _library_file(name, file).unlink()


def library_remove(name: str) -> None:
    """Удалить папку программы вместе с файлами."""
    folder = _library_folder(name)
    if not folder.is_dir():
        raise ValueError(f"папки «{name}» нет")
    shutil.rmtree(folder)


def slot_name(index: int, folder, media="photo") -> str:
    """Как назвать папку в сообщении: у фото слотов несколько (позиции
    карусели), у видео папка одна."""
    if media == "video":
        return f"папка с видео ({folder})"
    return f"папка-слот №{index + 1} ({folder})"


def list_slot_photos(folder, media="photo") -> list:
    """Свежий листинг папки слота: только файлы (не поддиректории) с
    расширением из PHOTO_EXTS (регистронезависимо), не рекурсивно;
    media="video" — ролики с расширением из VIDEO_EXTS.

    Захваченные параллельными воркерами файлы не показываются:
    переименованные (.claim_ в имени) и маркеры (имя кончается на .claim_).

    Сортировка простая лексикографическая по имени файла (регистронезависимо,
    ключ сортировки — .lower()). ОГРАНИЧЕНИЕ: "10.jpg" встанет раньше "2.jpg"
    при таком порядке — для строгого числового порядка нужны имена с
    ведущими нулями (001.jpg, 002.jpg, ..., 010.jpg).

    Если папки не существует или это не директория — возвращает пустой
    список (не бросает исключение — вызывающий код сам решает, что делать
    с пустым слотом).
    """
    folder = Path(folder)
    if not folder.is_dir():
        return []
    exts = MEDIA_EXTS.get(media, PHOTO_EXTS)
    files = [
        p for p in folder.iterdir()
        if p.is_file()
        and p.suffix.lower() in exts
        and ".claim_" not in p.name
    ]
    files.sort(key=lambda p: p.name.lower())
    return files


# «photo.claim_1234_7.jpg» -> исходное «photo.jpg»
_CLAIMED_RE = re.compile(r"^(?P<stem>.+)\.claim_(?P<pid>\d+)_\d+$")


def original_name(claimed) -> str:
    """Исходное имя захваченного файла ('' — имя не похоже на захват)."""
    p = Path(claimed)
    match = _CLAIMED_RE.match(p.stem)
    return f"{match.group('stem')}{p.suffix}" if match else ""


def release_stale(folders) -> int:
    """Вернуть в очередь захваты, оставшиеся от прошлых запусков.

    Захваченный файл выпадает из листинга, поэтому падение или закрытие
    программы между загрузкой и итогом поста прятало бы фото навсегда.
    Вызывается ОДИН РАЗ перед стартом прогона, до запуска воркеров: свои
    захваты (pid текущего процесса) и живые маркеры не трогает. Возвращает
    число восстановленных файлов."""
    restored = 0
    mine = str(os.getpid())
    for folder in folders or ():
        folder = Path(folder)
        if not folder.is_dir():
            continue
        names = {p.name for p in folder.iterdir() if p.is_file()}
        for p in folder.iterdir():
            if not p.is_file():
                continue
            if p.name.endswith(".claim_"):
                # маркер осиротел, только если рядом нет ни исходного файла,
                # ни захвата с тем же именем: иначе его держит живой воркер
                base = p.name[:-len(".claim_")]
                stem, _, suffix = base.rpartition(".")
                busy = base in names or any(
                    n.startswith(f"{stem}.claim_") and n.endswith(f".{suffix}")
                    for n in names)
                if not busy:
                    try:
                        p.unlink()
                    except OSError:
                        pass
                continue
            match = _CLAIMED_RE.match(p.stem)
            if not match or match.group("pid") == mine:
                continue
            target = p.with_name(f"{match.group('stem')}{p.suffix}")
            try:
                if not target.exists():
                    os.rename(p, target)
                    restored += 1
            except OSError as exc:
                print(f"[photo_source] не удалось вернуть {p.name}: {exc}")
    if restored:
        from . import eventlog
        eventlog.say(f"фото возвращены в папки после прошлого запуска: {restored}",
                     "", source="photo")
    return restored


_kept_cursor = {}
_kept_lock = threading.Lock()


def pick_kept(folder, media="photo"):
    """Следующее фото папки по кругу, без захвата; None — папка пуста."""
    photos = list_slot_photos(folder, media)
    if not photos:
        return None
    key = str(Path(folder).resolve())
    with _kept_lock:
        n = _kept_cursor.get(key, 0)
        _kept_cursor[key] = n + 1
    return photos[n % len(photos)]


def peek_next(folder):
    """Первый элемент свежего list_slot_photos(folder), или None если пусто."""
    photos = list_slot_photos(folder)
    return photos[0] if photos else None


def resolve_photo_path(path) -> Path:
    """Путь к папке или к файлу -> конкретный файл-фото.

    Папка (обычный случай, тот же принцип, что у папок-слотов батча) ->
    peek_next(path) — следующее доступное фото из неё; пусто -> FileNotFoundError
    с понятным текстом. Путь к конкретному файлу — работает как раньше,
    без изменений (оставлено для случаев, когда нужен именно этот файл, а
    не «следующий из очереди»). Ни того, ни другого — FileNotFoundError.
    """
    path = Path(path)
    if path.is_dir():
        nxt = peek_next(path)
        if nxt is None:
            raise FileNotFoundError(f"в папке нет фото: {path}")
        return nxt
    if path.is_file():
        return path
    raise FileNotFoundError(f"не найдено ни файла, ни папки: {path}")


class PhotoConsumeError(RuntimeError):
    """Ошибка при загрузке одного из фото в серии (одна публикация может
    требовать несколько фото-слотов — карусель). Несёт то, что уже успело
    произойти до сбоя, чтобы вызывающий код мог честно сообщить пользователю,
    какие файлы уже безвозвратно потрачены (удалены), а какие ещё целы.
    """

    def __init__(self, message, consumed, failed_path, index, *, stop_account=False,
                 outcome_unknown=False):
        super().__init__(message)
        self.consumed = consumed
        self.failed_path = str(failed_path)
        self.index = index
        self.stop_account = stop_account
        self.outcome_unknown = outcome_unknown


class PhotoClaimConflict(RuntimeError):
    """Файл успел захватить другой параллельный воркер (rename в claim
    проиграл). Не ошибка поста — вызывающий код берёт следующий файл слота."""


_claim_seq = 0
_claim_lock = threading.Lock()


def claim_photo(path) -> Path:
    """Атомарно захватывает фото за этим воркером.

    Двухфазный захват (rename в одиночку под нагрузкой Windows НЕ падает
    при гонке — проверено трейсом; O_EXCL — падает железно):
      1) marker = <имя>.claim_ — os.open(O_CREAT|O_EXCL): FileExistsError,
         если маркер уже создал другой воркер (он и является «своим»
         владельцем файла);
      2) rename фото в <имя>.claim_<pid>_<seq>.<ext> — файл уходит из
         листинга (листинг фильтрует .claim_ и маркеры).

    Захваченный файл грузится на TOS, а списывается по итогу поста
    (commit_photos — пост вышел, burn_photos — не вышел).

    Возвращает ПУТЬ К ЗАХВАЧЕННОМУ файлу. FileNotFoundError, если файл
    достался другому воркеру — вызывающий код берёт следующий из листинга.
    """
    p = Path(path)
    marker = p.with_name(p.name + ".claim_")
    try:
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        # маркер жив: файл обрабатывает (или доделывает) другой воркер
        raise FileNotFoundError(f"{p} уже захвачен (маркер {marker.name})")
    except PermissionError as exc:
        # Windows: маркер в этот момент удаляет другой воркер — файл висит в
        # состоянии delete pending, и создать его заново нельзя (Errno 13
        # вместо FileExistsError). Это та же гонка, ответ тот же: берём
        # следующий файл. Раньше ошибка улетала наверх и роняла воркер.
        raise FileNotFoundError(f"{p}: файл занят другим воркером ({exc})")

    with _claim_lock:
        global _claim_seq
        _claim_seq += 1
        seq = _claim_seq
    claimed = p.with_name(f"{p.stem}.claim_{os.getpid()}_{seq}{p.suffix}")
    try:
        os.rename(p, claimed)
        return claimed
    except (FileNotFoundError, PermissionError) as exc:
        # источник исчез или занят — маркер прочь, файл берёт другой
        try:
            marker.unlink()
        except OSError:
            pass
        raise FileNotFoundError(f"{p}: захват не удался ({exc})")


def _upload(path, data, session, media, kw) -> dict:
    """Загрузка одного файла поста: фото — байты после уникализатора, видео —
    сам файл с диска частями. kw["via"] = (username, прокси) — через наш
    сервер (modules/cloud.py): тогда в ответе пропуск для публикации, а не uri."""
    via = kw.pop("via")
    from . import cloud, remote
    try:
        if media == "video":
            return cloud.upload_video(*via, path)
        return cloud.upload_photo(*via, data if data is not None
                                  else uniq.render_file(path))
    except remote.RemoteError as exc:
        raise TOSUploadError(str(exc), stop_account=getattr(exc, "stop_account", False),
                             outcome_unknown=getattr(exc, "outcome_unknown", False)) from exc


def upload_claimed(path, session=None, media="photo", **kw) -> dict:
    """Захватывает файл и загружает его на TOS. Файл НЕ удаляет.

    1) claim_photo(path) — маркер O_EXCL + rename. Если файл уже захвачен
       другим воркером — FileNotFoundError ПРОБРАСЫВАЕТСЯ (это нормальный
       сигнал «возьми следующий», ловит вызывающий код батча).
    2) cloud.upload_photo(uniq.render_file(claimed)) — байты
       проходят уникализатор; TOSUploadError летит как есть, захваченный
       файл при этом удаляется: запрос ушёл, фото списано.
    3) Возвращает dict от cloud.upload_photo + {'path': исходный путь,
       'claimed': захваченный, 'deleted': False}.

    Судьбу файла решает вызывающий по итогу ПОСТА: commit_photos, если пост
    опубликован, burn_photos — если нет."""
    claimed = claim_photo(path)
    try:
        result = _upload(claimed, None, session, media, kw)
    except BaseException:
        # Запрос ушёл — фото списано, независимо от того, чем всё кончилось.
        # Обрыв, таймаут, неожиданный ответ: понять, дошло оно до TikTok или
        # нет, нельзя, а второй залив уже засветившегося фото — это тень на
        # следующем посте. Фоток заранее много, потеря одной дешевле.
        _burn_one(path, claimed)
        raise
    result = dict(result)
    result["path"] = str(path)
    result["claimed"] = str(claimed)
    result["deleted"] = False
    return result


def upload_shared(path, session=None, cache=None, media="photo", **kw) -> dict:
    """Фото, которое по итогу поста не удаляется: удержанное на прогон
    (hold_slot_photos) или из папки, которую велено не трогать (pick_kept).
    cache — «путь -> байты» на прогон: с ним во все посты уходит одна копия.
    Видео уходит файлом как есть, кэш ему не нужен."""
    data = None
    if media != "video":
        data = cache.get(str(path)) if cache is not None else None
        if data is None:
            data = uniq.render_file(path)
            if cache is not None:
                cache[str(path)] = data
    result = dict(_upload(path, data, session, media, kw))
    result["path"] = str(path)
    result["claimed"] = str(path)
    result["deleted"] = False
    result["keep"] = True  # commit_photos/burn_photos такие не трогают
    return result


def _drop_marker(path) -> None:
    """Снять маркер захвата исходного файла (его имя — <имя файла>.claim_)."""
    try:
        Path(str(path) + ".claim_").unlink()
    except OSError:
        pass


def _burn_one(path, claimed) -> bool:
    """Списать захваченный файл: удалить и снять маркер. True — удалён."""
    ok = False
    try:
        claimed = Path(claimed)
        if claimed.exists():
            claimed.unlink()
            ok = True
    except OSError as exc:
        print(f"[photo_source] не удалось удалить {claimed}: {exc}")
    _drop_marker(path)
    return ok


def _delete_claimed(items, why: str) -> int:
    """Удалить захваченные файлы. Возвращает число удалённых.

    Неудачный unlink не фатален: файл в листинг не вернётся (имя .claim_
    отфильтровано), максимум останется мусором на диске."""
    deleted = 0
    for item in items or ():
        if item.get("deleted") or item.get("keep"):
            continue  # keep — общий креатив, он нужен следующим аккаунтам
        claimed = Path(item.get("claimed") or item.get("path"))
        try:
            claimed.unlink()
            item["deleted"] = True
            deleted += 1
        except OSError as exc:
            print(f"[photo_source] не удалось удалить {claimed} ({why}): {exc}")
        _drop_marker(item.get("path"))
    return deleted


def commit_photos(items) -> int:
    """Пост опубликован — удалить захваченные файлы."""
    return _delete_claimed(items, "после публикации")


def burn_photos(items) -> int:
    """Фото дошли до серверов TikTok, но пост не вышел — тоже удалить.

    В очередь такие не возвращаются: файл уже засветился на стороне TikTok,
    и повторный залив тем же фото портит доверие к посту. Лучше потерять
    исходник, чем получить непонятную тень на следующем заливе.
    """
    return _delete_claimed(items, "залив не состоялся, фото уже ушло в TikTok")


def _held_origin(claimed) -> Path:
    """Исходный путь удержанного фото (по нему живёт маркер захвата)."""
    claimed = Path(claimed)
    return claimed.with_name(original_name(claimed) or claimed.name)


def hold_slot_photos(folders, media="photo") -> list:
    """Режим одинаковых креативов: захватить по одному фото из каждой
    папки-слота на весь прогон аккаунта.

    Все посты аккаунта уходят с этим комплектом, следующему аккаунту
    достаётся следующее фото слота — одинаковые креативы означают «одно фото
    на один залив», а не «одно фото на все аккаунты».

    Захват делается один раз до первого поста, и именно он разводит
    параллельные воркеры: удержанный файл выпадает из листинга, поэтому
    сосед физически возьмёт другой. Файлы берутся по порядку листинга, без
    разнесения стартов: захват атомарен и идёт ДО первой загрузки, поэтому
    проигравшему в гонке (FileNotFoundError от claim_photo) достаётся
    следующий файл, и это не стоит ничего кроме лишнего rename. Зато папка
    расходуется предсказуемо — с начала.

    Пустая папка или разобранная соседями до последнего файла —
    FileNotFoundError с номером слота: вызывающий останавливает прогон, а
    всё, что успело удержаться, возвращается в очередь (загрузок ещё не
    было, терять нечего). Возвращает list[Path] захваченных файлов, по
    одному на папку, в порядке папок."""
    held = []
    try:
        for index, folder in enumerate(folders or ()):
            photos = list_slot_photos(folder, media)
            if not photos:
                raise FileNotFoundError(f"{slot_name(index, folder, media)} пуста")
            claimed = None
            for candidate in photos:
                try:
                    claimed = claim_photo(candidate)
                    break
                except FileNotFoundError:
                    continue  # файл достался соседу, пробуем следующий
            if claimed is None:
                raise FileNotFoundError(
                    f"{slot_name(index, folder, media)}: свободных "
                    f"{MEDIA_WORD.get(media, 'фото')} не осталось, всё разобрали "
                    f"параллельные воркеры")
            held.append(claimed)
    except BaseException:
        return_held(held)
        raise
    return held


def release_held(claimed_paths) -> int:
    """Списать удержанные фото: удалить файлы и снять маркеры.

    Зовётся на выходе воркера, который хотя бы раз залил этот комплект в
    TikTok. В очередь такие не возвращаются по общему правилу модуля: запрос
    ушёл — фото потрачено. Возвращает число удалённых файлов."""
    deleted = 0
    for claimed in claimed_paths or ():
        if _burn_one(_held_origin(claimed), claimed):
            deleted += 1
    return deleted


def return_held(claimed_paths) -> int:
    """Вернуть удержанные фото в очередь под исходными именами.

    Только для случая, когда ни одной загрузки с этим комплектом не было:
    прогон закрыли сразу после захвата или он сорвался на соседнем слоте.
    Возвращает число восстановленных файлов."""
    returned = 0
    for claimed in claimed_paths or ():
        claimed = Path(claimed)
        origin = _held_origin(claimed)
        try:
            if origin != claimed and claimed.exists() and not origin.exists():
                os.rename(claimed, origin)
                returned += 1
        except OSError as exc:
            print(f"[photo_source] не удалось вернуть {claimed.name}: {exc}")
        _drop_marker(origin)
    return returned


def _prepare_photos_via(paths, consume, cache, via) -> list:
    """prepare_post_photos для фото через наш сервер: захватить и отрисовать
    все фото поста, пропуска на все одним запросом (cloud.upload_photos),
    потом залить по одному. Размер фото известен только после уникализатора,
    а пропуск выдаётся под размер, — поэтому сначала все отрисовать.

    Списывается только то, что начало уходить в TikTok. Не дошло до залива
    (сорвался запрос пропусков, залив раньше этого фото) — фото возвращается
    в очередь: TikTok его не видел."""
    from . import cloud, remote
    items, blobs = [], []

    def give_back(rest) -> None:
        return_held([it["claimed"] for it in rest if not it.get("keep")])

    for path in paths:
        if not consume:
            data = cache.get(str(path)) if cache is not None else None
            if data is None:
                data = uniq.render_file(path)
                if cache is not None:
                    cache[str(path)] = data
            items.append({"path": str(path), "claimed": str(path), "deleted": False,
                          "keep": True})  # commit_photos/burn_photos такие не трогают
            blobs.append(data)
            continue
        try:
            claimed = claim_photo(path)
        except FileNotFoundError as exc:
            # файл забрал параллельный воркер — сигнал батчу «возьми
            # следующий»; захваченные раньше в TikTok ещё не уходили
            give_back(items)
            raise PhotoClaimConflict(str(path)) from exc
        try:
            blobs.append(uniq.render_file(claimed))
        except BaseException:
            _burn_one(path, claimed)  # не читается — в очередь его незачем
            give_back(items)
            raise
        items.append({"path": str(path), "claimed": str(claimed), "deleted": False})

    sent = []
    try:
        ups = cloud.upload_photos(*via, blobs, sent=sent)
    except BaseException as exc:
        burn_photos(items[:len(sent)])
        give_back(items[len(sent):])
        if isinstance(exc, (remote.RemoteError, TOSUploadError)):
            index = max(len(sent) - 1, 0)
            raise PhotoConsumeError(str(exc), consumed=[], failed_path=paths[index],
                                    index=index, stop_account=getattr(exc, "stop_account", False),
                                    outcome_unknown=getattr(exc, "outcome_unknown", False)) from exc
        raise
    for item, up in zip(items, ups):
        item.update(up)
    return items


def prepare_post_photos(paths, session=None, username=None, consume=True,
                        cache=None, media="photo", **kw) -> list:
    """Захватывает и загружает на TOS файлы одного поста, по порядку.

    consume=False — режим одинаковых креативов: в paths приходят уже
    удержанные на весь прогон аккаунта файлы (hold_slot_photos), поэтому
    заново их не захватывают и по итогу поста не удаляют (upload_shared),
    их спишет release_held на выходе воркера.

    Файлы остаются на диске под .claim_-именами: удалит их commit_photos
    после успешной публикации либо burn_photos, если пост не вышел — фото
    уже дошло до TikTok, и в очередь оно не возвращается. Вызывающий ОБЯЗАН
    сделать одно из двух — иначе фото повиснут вне очереди до следующего
    запуска (там их подберёт release_stale).

    При первой же ошибке (TOSUploadError, конфликт захвата) немедленно
    останавливается: уже загруженные файлы этого поста возвращаются в
    очередь, дальше летит PhotoConsumeError/PhotoClaimConflict. Ни один
    файл при этом не потерян — поле consumed в исключении оставлено для
    совместимости и всегда пусто.

    Возвращает list[dict] — по одному на каждый path, в том же порядке,
    если всё прошло успешно.

    Фото через наш сервер (kw["via"]) — одним заходом, см. _prepare_photos_via.
    """
    paths = list(paths)
    if kw.get("via") and media == "photo":
        return _prepare_photos_via(paths, consume, cache, kw["via"])
    consumed = []
    for index, path in enumerate(paths):
        try:
            item = (upload_claimed(path, session=session, media=media, **kw) if consume
                    else upload_shared(path, session=session, cache=cache,
                                       media=media, **kw))
        except FileNotFoundError as exc:
            # файл уже захвачен параллельным воркером (или исчез) —
            # сигнал батчу «возьми следующий из слота», пост не рушим.
            # Уже загруженные на TOS не возвращаем: они засветились в
            # TikTok, их доверие потрачено (см. burn_photos).
            burn_photos(consumed)
            raise PhotoClaimConflict(str(path)) from exc
        except TOSUploadError as exc:
            burn_photos(consumed)
            raise PhotoConsumeError(
                str(exc), consumed=[], failed_path=path, index=index,
                stop_account=getattr(exc, "stop_account", False),
                outcome_unknown=getattr(exc, "outcome_unknown", False),
            ) from exc
        consumed.append(item)
    return consumed
