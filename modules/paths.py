"""Context-local data paths for normal execution and isolated tests."""
import contextlib
import contextvars
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_root = contextvars.ContextVar("data_root", default=ROOT)


def here(path: Path) -> Path:
    """Путь внутри текущего корня данных. Путь не из корня проекта (тест
    подменил константу на временный файл) — как есть."""
    root = _root.get()
    if root is ROOT:
        return path
    try:
        return root / Path(path).relative_to(ROOT)
    except ValueError:
        return path


@contextlib.contextmanager
def use_root(path):
    """На время блока данные живут в `path`, а не в корне проекта."""
    token = _root.set(Path(path))
    try:
        yield
    finally:
        _root.reset(token)
