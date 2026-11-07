# -*- coding: utf-8 -*-
"""Кеш config.load() по отпечатку файла: правки видны сразу, объекты не общие.

Запуск: Run the corresponding check in tests/.
config.json не трогается.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules import config  # noqa: E402


def _age(path, seconds):
    """Состарить файл: свежий в кеш не кладётся (см. _CACHE_SETTLE_NS)."""
    stamp = time.time() - seconds
    os.utime(path, (stamp, stamp))


def main():
    reads = []
    real_read = Path.read_text

    def counting(self, *a, **kw):
        if self.name == "config.json":
            reads.append(1)
        return real_read(self, *a, **kw)

    with tempfile.TemporaryDirectory() as tmp:
        config.CONFIG_FILE = Path(tmp) / "config.json"
        Path.read_text = counting
        try:
            f = config.CONFIG_FILE
            f.write_text('{"port": 1111}', encoding="utf-8")
            _age(f, 20)

            assert config.load()["port"] == 1111
            n = len(reads)
            assert config.load()["port"] == 1111 and len(reads) == n, "повторное чтение не из кеша"

            # внешняя правка того же размера, mtime другой -> перечитали
            f.write_text('{"port": 2222}', encoding="utf-8")
            _age(f, 10)
            assert config.load()["port"] == 2222, "внешняя правка не подхвачена"

            # мутация результата не портит следующий load (вложенное тоже)
            f.write_text('{"proxies": ["a"], "flags": {"posts_per_account": 3}}',
                         encoding="utf-8")
            _age(f, 30)
            a = config.load()
            a["proxies"].append("evil")
            a["flags"]["posts_per_account"] = 99
            a["uniq"]["enabled"] = "x"
            b = config.load()
            assert b["proxies"] == ["a"] and b["flags"]["posts_per_account"] == 3, b
            assert b["uniq"]["enabled"] is True and config.DEFAULTS["uniq"]["enabled"] is True
            assert a is not b

            # update -> следующий load видит новое
            config.update({"port": 3333})
            assert config.load()["port"] == 3333
            config.update({"flags": {"posts_per_account": 7}})
            got = config.load()
            assert got["flags"]["posts_per_account"] == 7 and got["proxies"] == ["a"]

            # save и write_text_atomic в config.json тоже сбрасывают кеш
            _age(f, 40)
            config.load()
            config.save({"port": 4444})
            assert config.load()["port"] == 4444
            _age(f, 40)
            config.load()
            config.write_text_atomic(f, '{"port": 5555}')
            assert config.load()["port"] == 5555

            # нет файла -> создаётся с дефолтами
            f.unlink()
            assert config.load()["port"] == config.DEFAULTS["port"] and f.exists()
        finally:
            Path.read_text = real_read
            config._drop_cache()
    print("config cache: OK")


if __name__ == "__main__":
    main()
