"""Local SQLite storage."""
import sqlite3
import threading
from pathlib import Path

from . import paths

BASE = Path(__file__).resolve().parent.parent
DB_FILE = BASE / "data.db"

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS avatars ("
    " username TEXT PRIMARY KEY,"
    " data TEXT NOT NULL,"
    " updated_at INTEGER NOT NULL,"
    " src TEXT)",                       # с какой картинки скачана (путь ссылки без подписи)

    "CREATE TABLE IF NOT EXISTS profiles ("
    " username TEXT PRIMARY KEY,"
    " method TEXT NOT NULL,"            # detail | ssr — каким способом получен
    " user_id TEXT,"
    " sec_uid TEXT,"
    " unique_id TEXT,"
    " nickname TEXT,"
    " signature TEXT,"                  # описание профиля
    " verified INTEGER,"
    " private_account INTEGER,"
    " followers INTEGER,"
    " following INTEGER,"
    " friends INTEGER,"
    " likes INTEGER,"                   # лайки на постах аккаунта (heart)
    " liked INTEGER,"                   # сколько лайков поставил сам (diggCount)
    " videos INTEGER,"
    " created_at INTEGER,"              # дата регистрации — только способ ssr
    " is_organization INTEGER,"         # только ssr
    " language TEXT,"                   # только ssr
    " fetched_at INTEGER NOT NULL)",

    "CREATE TABLE IF NOT EXISTS posts ("
    " item_id TEXT PRIMARY KEY,"
    " username TEXT NOT NULL,"
    " created_at INTEGER,"
    " description TEXT,"
    " is_photo INTEGER,"
    " views INTEGER,"
    " likes INTEGER,"
    " comments INTEGER,"
    " shares INTEGER,"
    " saves INTEGER,"
    " reposts INTEGER,"
    " shadow INTEGER,"                  # 1 — в тени, 0 — нет, NULL — не проверяли
    " fetched_at INTEGER NOT NULL)",

    "CREATE INDEX IF NOT EXISTS posts_by_username ON posts (username, created_at)",
)

_init_lock = threading.Lock()
_ready_for = set()  # пути баз, для которых схема уже создана


def _migrate(conn: sqlite3.Connection) -> None:
    """profiles первой версии хранил ответ TikTok одной JSON-строкой (колонка
    data). Там только кэш, который заново забирает «Обновить профили», —
    пересоздаём таблицу по колонкам, аватарки не трогаем.

    posts без колонки shadow — дописываем её: посты остаются, признак тени
    появится у них со следующим обновлением профилей. Так же avatars без src:
    картинки остаются, при следующем обновлении каждая скачается ещё раз."""
    cols = [row[1] for row in conn.execute("PRAGMA table_info(profiles)")]
    if "data" in cols:
        conn.execute("DROP TABLE profiles")
    cols = [row[1] for row in conn.execute("PRAGMA table_info(posts)")]
    if cols and "shadow" not in cols:
        conn.execute("ALTER TABLE posts ADD COLUMN shadow INTEGER")
    cols = [row[1] for row in conn.execute("PRAGMA table_info(avatars)")]
    if cols and "src" not in cols:
        conn.execute("ALTER TABLE avatars ADD COLUMN src TEXT")


def connect() -> sqlite3.Connection:
    """Новое соединение; схема — при первом обращении к этому файлу."""
    path = paths.here(DB_FILE)
    conn = sqlite3.connect(str(path), timeout=10)
    if path not in _ready_for:
        with _init_lock:
            if path not in _ready_for:
                _migrate(conn)
                for stmt in _SCHEMA:
                    conn.execute(stmt)
                conn.commit()
                # сервер заводит временную папку на каждый запрос (paths.use_root):
                # набор не должен расти без конца — сброс лишь повторит
                # идемпотентное «CREATE TABLE IF NOT EXISTS»
                if len(_ready_for) > 256:
                    _ready_for.clear()
                _ready_for.add(path)
    return conn
