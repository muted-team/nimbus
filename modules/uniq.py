# -*- coding: utf-8 -*-
"""Уникализатор фото перед заливом в TikTok: настройки в config.json, ключ "uniq"."""
import base64
import io
import math
import os
import random
import re
import threading
from pathlib import Path

from PIL import Image, ImageEnhance, ImageOps
from PIL.ExifTags import GPSTAGS, IFD, TAGS
from pillow_heif import register_heif_opener

from . import config

# HEIC/HEIF с айфона: Pillow сам их не открывает
register_heif_opener()

ROTATE_LIMIT = 360
PREVIEW_SIDE = 1080
QUALITY_LIMIT = 100
SCALE_LIMIT = 100

# форматы, которые сохраняем как есть; остальное (MPO с телефонов и т.п.) — JPEG
_SAVE = {
    "JPEG": {"quality": 95},
    "PNG": {},
    "WEBP": {"quality": 95},
}

# без обработки в TikTok уходит исходный файл только этих форматов (MPO — JPEG
# с айфона); HEIC, AVIF, BMP и прочие он не примет — их перекодируем в JPEG
# даже при выключенном уникализаторе
_AS_IS = {"JPEG", "MPO", "PNG", "WEBP"}

# Pillow их узнаёт, но картинку не достаёт: заглушки без внешнего обработчика
# (BUFR, GRIB, HDF5, WMF), MPEG — это видео, EPS нужен Ghostscript
_NO_PIXELS = {"BUFR", "EPS", "GRIB", "HDF5", "MPEG", "WMF"}

# расширения фото в папках-слотах: всё, что Pillow умеет открыть
PHOTO_EXTS = frozenset(ext for ext, fmt in Image.registered_extensions().items()
                       if fmt in Image.OPEN and fmt not in _NO_PIXELS)

# Сколько фото обрабатываются разом. Обработка — самая тяжёлая работа публикации
# на этой машине: фото распаковывается целиком, а под поворот ещё и на холст
# втрое шире и выше. Потоков публикации бывает куда больше, чем ядер (до
# config.THREADS_MAX), и без предела все аккаунты обрабатывали фото одновременно.
# Замер regression checks, 200 аккаунтов на 12 ядрах: пик памяти 7034 МБ,
# ответ окну до 13915 мс. С пределом в половину ядер — 317 МБ и до 294 мс, а весь
# залп дольше на 8 с из 31: быстрее не выйдет, ядер столько нет. Половина, а не
# все: остальное нужно серверу, окну и сети.
RENDER_SLOTS = max(1, (os.cpu_count() or 2) // 2)
_render_slots = threading.BoundedSemaphore(RENDER_SLOTS)


def _int_in(value, lo: int, hi: int, default: int) -> int:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError, OverflowError):
        return default
    return max(lo, min(hi, number))


def _param(raw, default_min: int, default_max: int,
           lo: int, hi: int, enabled: bool = False) -> dict:
    """Диапазонный параметр: {enabled, locked, min, max} с зажатыми границами."""
    raw = raw if isinstance(raw, dict) else {}
    a = _int_in(raw.get("min"), lo, hi, default_min)
    b = _int_in(raw.get("max"), lo, hi, default_max)
    if a > b:
        a, b = b, a
    return {
        # locked — только замок от случайного сдвига в интерфейсе, на обработку не влияет
        "enabled": bool(raw.get("enabled", enabled)),
        "locked": bool(raw.get("locked", False)),
        "min": a,
        "max": b,
    }


def normalize(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    return {
        "enabled": bool(raw.get("enabled", True)),
        "rotate": _param(raw.get("rotate"), 0, 0, -ROTATE_LIMIT, ROTATE_LIMIT),
        # сжатие переводит фото в JPEG; качество — диапазон, на залив берётся случайно
        "compress": _param(raw.get("compress"), 85, 95, 1, QUALITY_LIMIT, enabled=True),
        # цветовые сдвиги — проценты от нормы; гамма — шаги по 0,01 от единицы;
        # цвет — поворот палитры по кругу в градусах; масштаб — приближение
        # в процентах (отдалять нельзя — полезли бы пустые рамки)
        "brightness": _param(raw.get("brightness"), -3, 3, -100, 100),
        "contrast": _param(raw.get("contrast"), -3, 3, -100, 100),
        "saturation": _param(raw.get("saturation"), -5, 5, -100, 100),
        "gamma": _param(raw.get("gamma"), -2, 2, -10, 10),
        "hue": _param(raw.get("hue"), -3, 3, -180, 180),
        "scale": _param(raw.get("scale"), 0, 3, 0, SCALE_LIMIT),
    }


def load() -> dict:
    return normalize(config.get("uniq"))


def update(patch) -> dict:
    state = load()
    if isinstance(patch, dict):
        if "enabled" in patch:
            state["enabled"] = patch["enabled"]
        for key in ("rotate", "compress", "brightness", "contrast",
                    "saturation", "gamma", "hue", "scale"):
            if isinstance(patch.get(key), dict):
                state[key].update(patch[key])
    state = normalize(state)
    config.update({"uniq": state})
    return state


def pick(state: dict) -> dict:
    """Параметры одного залива: случайны из своих диапазонов (качество сжатия —
    целым); пусто — фото уходит нетронутым."""
    if not state["enabled"]:
        return {}
    applied = {}
    for key in ("rotate", "scale", "brightness", "contrast",
                "saturation", "gamma", "hue"):
        p = state[key]
        if p["enabled"]:
            applied[key] = round(random.uniform(p["min"], p["max"]), 2)
    comp = state["compress"]
    if comp["enabled"]:
        applied["compress"] = random.randint(comp["min"], comp["max"])
    return applied


def _mirror_canvas(img: Image.Image, pad_x: int, pad_y: int) -> Image.Image:
    # соседние плитки отражены — шва нет; узкой панораме на 90° одной копии с краю мало
    w, h = img.size
    tiles = {
        (False, False): img,
        (True, False): img.transpose(Image.Transpose.FLIP_LEFT_RIGHT),
        (False, True): img.transpose(Image.Transpose.FLIP_TOP_BOTTOM),
        (True, True): img.transpose(Image.Transpose.ROTATE_180),
    }
    canvas = Image.new(img.mode, (w + 2 * pad_x, h + 2 * pad_y))
    nx = -(-pad_x // w)
    ny = -(-pad_y // h)
    for j in range(-ny, ny + 1):
        for i in range(-nx, nx + 1):
            canvas.paste(tiles[(i % 2 == 1, j % 2 == 1)], (pad_x + i * w, pad_y + j * h))
    return canvas


def _rotate(img: Image.Image, angle: float) -> Image.Image:
    """По часовой стрелке, размер тот же, пустые углы — зеркало снимка."""
    if angle % 360 == 0:
        return img
    w, h = img.size
    rad = math.radians(angle)
    c, s = abs(math.cos(rad)), abs(math.sin(rad))
    # +2 px — запас под ядро бикубической интерполяции
    pad_x = max(0, math.ceil((w * c + h * s - w) / 2)) + 2
    pad_y = max(0, math.ceil((w * s + h * c - h) / 2)) + 2
    canvas = _mirror_canvas(img, pad_x, pad_y)
    turned = canvas.rotate(-angle, resample=Image.Resampling.BICUBIC,
                           center=(pad_x + w / 2, pad_y + h / 2))
    return turned.crop((pad_x, pad_y, pad_x + w, pad_y + h))


def _hue(img: Image.Image, degrees: float) -> Image.Image:
    """Поворот палитры по цветовому кругу: вся гамма уезжает на столько
    градусов. Альфа не трогается."""
    bands = img.split()
    h, s, v = Image.merge("RGB", bands[:3]).convert("HSV").split()
    # H в Pillow — байт 0..255 на полный круг 360°
    shift = round(degrees * 255 / 360) % 256
    h = h.point([(i + shift) % 256 for i in range(256)])
    rgb = Image.merge("HSV", (h, s, v)).convert("RGB").split()
    return Image.merge(img.mode, (*rgb, *bands[3:]))


def _tone(img: Image.Image, applied: dict) -> Image.Image:
    """Цветовые сдвиги: яркость, контраст, насыщенность — проценты от нормы,
    гамма — тоновая кривая шагами 0,01 от единицы, цвет — поворот палитры.
    Альфа не трогается."""
    for key, enhance in (("brightness", ImageEnhance.Brightness),
                         ("contrast", ImageEnhance.Contrast),
                         ("saturation", ImageEnhance.Color)):
        if key in applied:
            img = enhance(img).enhance(1 + applied[key] / 100)
    if "hue" in applied:
        img = _hue(img, applied["hue"])
    if "gamma" in applied:
        gamma = 1 + applied["gamma"] / 100
        lut = [round(255 * (i / 255) ** gamma) for i in range(256)]
        # point() на многоканальном изображении хочет таблицу на каждый канал,
        # а альфу гаммой трогать нельзя — цвет отдельно, альфа как была
        bands = img.split()
        rgb = Image.merge("RGB", bands[:3]).point(lut * 3).split()
        img = Image.merge(img.mode, (*rgb, *bands[3:]))
    return img


def _scale(img: Image.Image, pct: float) -> Image.Image:
    """Приближение: картинка растёт на pct процентов, края срезаются, размер
    на выходе тот же. Только вперёд — отдалённая картинка потребовала бы
    пустых рамок по краям."""
    if not pct:
        return img
    w, h = img.size
    big = img.resize((round(w * (1 + pct / 100)), round(h * (1 + pct / 100))),
                     Image.Resampling.LANCZOS)
    x = (big.width - w) // 2
    y = (big.height - h) // 2
    return big.crop((x, y, x + w, y + h))


def apply(img: Image.Image, applied: dict) -> Image.Image:
    if img.mode not in ("RGB", "RGBA"):
        alpha = "A" in img.getbands() or "transparency" in img.info
        img = img.convert("RGBA" if alpha else "RGB")
    if "scale" in applied:
        img = _scale(img, applied["scale"])
    if "rotate" in applied:
        img = _rotate(img, applied["rotate"])
    img = _tone(img, applied)
    return img


def _to_rgb(img: Image.Image) -> Image.Image:
    """JPEG альфы не умеет: настоящая прозрачность ложится на белое."""
    if img.mode == "RGBA" and img.getchannel("A").getextrema()[0] < 255:
        flat = Image.new("RGB", img.size, (255, 255, 255))
        flat.paste(img, mask=img.getchannel("A"))
        return flat
    return img.convert("RGB")


def _render(path, applied: dict):
    """Обработанное фото: картинка, формат и параметры сохранения.

    Порядок важен: поворот идёт по распакованным пикселям в памяти, а
    кодирование (в том числе JPEG со сжатием) — последняя операция и
    единственная, двойной потери качества не возникает."""
    with Image.open(path) as src:
        # сжатие переводит в JPEG: PNG того же вида в разы тяжелее
        fmt = "JPEG" if "compress" in applied else (src.format if src.format in _SAVE else "JPEG")
        # цветовой профиль переносим, иначе снимки в Display P3 потускнеют
        params = dict(_SAVE[fmt], icc_profile=src.info.get("icc_profile"))
        if "compress" in applied:
            params["quality"] = applied["compress"]
        # поворот из EXIF запекаем в пиксели: метаданные в новый файл не идут
        img = ImageOps.exif_transpose(src)
    img = apply(img, applied)
    if fmt == "JPEG" and img.mode != "RGB":
        img = _to_rgb(img)
    return img, fmt, params


def _as_is(path) -> bool:
    """Исходный файл годится TikTok без перекодирования. Формат смотрим по
    содержимому: HEIC с айфона бывает переименован в .jpg."""
    with Image.open(path) as src:
        return src.format in _AS_IS


def render_file(path) -> bytes:
    """Байты фото для залива: уникализированные либо исходные, если обрабатывать нечего.

    Обработка ждёт свободного места (RENDER_SLOTS). Предпросмотр (preview) мимо
    очереди: он один, его ждёт человек, а место в очереди за сотней аккаунтов
    освободилось бы через полминуты."""
    path = Path(path)
    applied = pick(load())
    if not applied and _as_is(path):
        return path.read_bytes()
    with _render_slots:
        img, fmt, params = _render(path, applied)
        buf = io.BytesIO()
        img.save(buf, fmt, **params)
    print(f"[uniq] {path.name}: {applied}")
    return buf.getvalue()


def _num(x, nd: int = 2) -> str:
    """Число строкой: есть дробная часть — с запятой, целое — без неё."""
    s = f"{float(x):.{nd}f}".rstrip("0").rstrip(".")
    return s.replace(".", ",")


def _size(n: int) -> str:
    if n < 1048576:
        return f"{n // 1024} КБ"
    return _num(n / 1048576) + " МБ"


def _fmt_val(x) -> str:
    """Значение метаданных строкой: байты — как текст либо размер, рационалы
    EXIF — дробью или десятично, кортежи — через запятую."""
    if isinstance(x, bytes):
        try:
            s = x.decode("utf-8")
            if s.isprintable() and s.strip():
                return s.strip()[:100]
        except UnicodeDecodeError:
            pass
        return f"{len(x)} байт"
    if isinstance(x, tuple):
        return ", ".join(_fmt_val(v) for v in x)
    if not isinstance(x, (bool, int, float)):  # у чисел тоже есть numerator/denominator
        num, den = getattr(x, "numerator", None), getattr(x, "denominator", None)
        if num is not None and den is not None and den > 0:
            return f"{num}/{den}" if 0 < num < den else _num(x)
    return str(x)[:100]


# '2024:09:12 20:03:15' — так EXIF хранит даты
_DATE_RE = re.compile(r"^(\d+):(\d+):(\d+) (\d+):(\d+)")


def _meta(img: Image.Image, size: int) -> dict:
    """Все метаданные фото для предпросмотра: базовые свойства, info-ключи
    PIL, весь EXIF по всем IFD, XMP и цветовой профиль. size — вес файла в
    байтах (у итоговых байтов пути на диске нет). Порядок строк — порядок
    отображения."""
    meta = {}
    w, h = img.size
    meta["Размер"] = f"{w}×{h} ({_num(w * h / 1e6)} МП)"
    if img.format:
        meta["Формат"] = f"{img.format} {img.mode}"
    meta["Вес"] = _size(size)
    if "A" in img.getbands() or "transparency" in img.info:
        meta["Прозрачность"] = "есть"
    frames = getattr(img, "n_frames", 1)
    if frames > 1:
        meta["Кадры"] = str(frames)

    # info-ключи PIL: текстовые чанки PNG, гамма, XMP и прочее; известные
    # бинарные обрабатываем отдельно, остальное — как есть
    for key, val in img.info.items():
        if key in ("icc_profile", "exif", "dpi", "transparency", "gamma",
                   "XML:com.adobe.xmp"):
            continue
        if not isinstance(val, bytes):
            meta[key] = _fmt_val(val)
    dpi = img.info.get("dpi")
    if dpi and dpi[0]:
        meta["DPI"] = f"{int(round(float(dpi[0])))}×{int(round(float(dpi[1])))}"
    gamma = img.info.get("gamma")
    if gamma:
        meta["Гамма"] = _fmt_val(gamma)
    xmp = img.info.get("XML:com.adobe.xmp")
    if xmp:
        meta["XMP"] = f"{len(xmp)} байт"

    try:
        exif = img.getexif()
    except Exception:  # noqa: BLE001 — битый EXIF не должен ронять предпросмотр
        exif = None

    def dump_ifd(ifd, prefix="", gps=False):
        for tag, val in ifd.items():
            if tag in (34665, 34853, 40965):  # указатели на вложенные IFD — не данные
                continue
            # в GPS-IFD имена ищем в GPSTAGS первыми: у тега 1 они конфликтуют
            name = (GPSTAGS.get(tag) or TAGS.get(tag) if gps
                    else TAGS.get(tag) or GPSTAGS.get(tag)) or f"#{tag}"
            if gps and tag in (2, 4) and isinstance(val, tuple) and len(val) == 3:
                val = "{}° {}' {}\"".format(*(_fmt_val(x) for x in val))
            if "Date" in name or "Time" in name:
                m = _DATE_RE.match(str(val) if not isinstance(val, (tuple, bytes)) else "")
                if m:
                    val = f"{m.group(3)}.{m.group(2)}.{m.group(1)} {m.group(4)}:{m.group(5)}"
            meta[prefix + str(name)] = _fmt_val(val)

    if exif is not None:
        dump_ifd(exif)
        for ifd_name, prefix, gps in ((IFD.Exif, "", False), (IFD.GPSInfo, "", True),
                                      (IFD.Interop, "Interop: ", False)):
            try:
                sub = exif.get_ifd(ifd_name)
            except Exception:  # noqa: BLE001 — не у всех файлов есть все IFD
                sub = None
            if sub:
                dump_ifd(sub, prefix, gps)

    icc = img.info.get("icc_profile")
    if icc:
        size = f"{len(icc)} байт" if len(icc) < 1024 else _size(len(icc))
        name = next((n for n in (b"sRGB", b"Display P3", b"Adobe RGB") if n in icc), None)
        meta["Цветовой профиль"] = f"{name.decode('ascii')}, {size}" if name else size
    return meta


def preview(folder, state: dict) -> dict:
    """Первое фото папки по state: картинка для экрана и метаданные того, что
    уйдёт в TikTok — уникализированные байты, а без обработки исходный файл;
    из очереди фото не забирается."""
    from .photo_source import list_slot_photos
    photos = list_slot_photos(folder)
    if not photos:
        raise FileNotFoundError("в папке нет фото")
    path = photos[0]
    applied = pick(state)
    if applied or not _as_is(path):
        img, fmt, params = _render(path, applied)
        buf = io.BytesIO()
        img.save(buf, fmt, **params)
        size = len(buf.getbuffer())
        # метаданные читаем с итоговых байтов: что реально уйдёт в TikTok
        buf.seek(0)
        with Image.open(buf) as out:
            meta = _meta(out, size)
    else:
        # обрабатывать нечего: уйдёт исходный файл как есть
        with Image.open(path) as src:
            size = path.stat().st_size
            meta = _meta(src, size)
            img = ImageOps.exif_transpose(src)
    img.thumbnail((PREVIEW_SIDE, PREVIEW_SIDE))
    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=90)
    return {"image": "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode("ascii"),
            "name": path.name,
            "applied": applied,
            "bytes": size,
            "meta": meta}
