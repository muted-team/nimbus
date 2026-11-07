# -*- coding: utf-8 -*-
"""Что за видео лежит на диске — без декодера и без TikTok: размер кадра,
длительность, есть ли звук. Нужен и клиенту сервера (он сам льёт файлы и
сообщает серверу кадр), и прежнему пути публикации (video_upload)."""

import struct

# форматы в папке с видео: студия рекомендует .mp4 и принимает «другие
# основные» — берём те, что реально ходят с телефонов и монтажек
VIDEO_EXTS = frozenset({".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"})


# ============================================================================
# Метаданные MP4/MOV без декодера: размер кадра, длительность, есть ли звук
# ============================================================================

def _boxes(f, start: int, end: int):
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        size, kind = struct.unpack(">I4s", f.read(8))
        head = 8
        if size == 1:
            size = struct.unpack(">Q", f.read(8))[0]
            head = 16
        elif size == 0:
            size = end - pos
        if size < head:
            return
        yield kind, pos + head, pos + size
        pos += size


def _child(f, start, end, kind):
    return next(((s, e) for k, s, e in _boxes(f, start, end) if k == kind), None)


def mp4_info(path) -> dict | None:
    """{width, height, duration_ms, has_audio} из moov MP4/MOV; None — не MP4
    или разобрать не вышло. Поворот из матрицы tkhd учитывается: телефонное
    вертикальное видео хранится кадром 1920×1080 с поворотом на 90°."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            moov = _child(f, 0, f.tell(), b"moov")
            if not moov:
                return None
            out = {"width": 0, "height": 0, "duration_ms": 0, "has_audio": False}
            for kind, s, e in _boxes(f, *moov):
                if kind != b"trak":
                    continue
                mdia = _child(f, s, e, b"mdia")
                hdlr = mdia and _child(f, *mdia, b"hdlr")
                mdhd = mdia and _child(f, *mdia, b"mdhd")
                if not (hdlr and mdhd):
                    continue
                f.seek(hdlr[0] + 8)
                handler = f.read(4)
                if handler == b"soun":
                    out["has_audio"] = True
                    continue
                if handler != b"vide" or out["width"]:
                    continue
                f.seek(mdhd[0])
                if f.read(1)[0] == 1:
                    f.seek(mdhd[0] + 20)
                    timescale, duration = struct.unpack(">IQ", f.read(12))
                else:
                    f.seek(mdhd[0] + 12)
                    timescale, duration = struct.unpack(">II", f.read(8))
                tkhd = _child(f, s, e, b"tkhd")
                if not tkhd or not timescale:
                    continue
                f.seek(tkhd[1] - 44)
                matrix = struct.unpack(">9i", f.read(36))
                w, h = (v / 65536 for v in struct.unpack(">II", f.read(8)))
                if matrix[0] == 0 and matrix[1] != 0:  # поворот на 90/270
                    w, h = h, w
                out.update(width=round(w), height=round(h),
                           duration_ms=round(duration * 1000 / timescale))
            return out if out["width"] and out["duration_ms"] else None
    except (OSError, struct.error, IndexError, ValueError):
        return None
