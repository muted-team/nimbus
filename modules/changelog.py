"""Parse user-facing release notes. Versions change only when a release is prepared."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG_FILE = ROOT / "CHANGELOG.md"

# «## 1.0.3 — 13.09.2026»: тире любое, «v» перед номером допускается
_HEAD_RE = re.compile(r"^##\s+v?(\d+)\.(\d+)\.(\d+)\s*[—–-]\s*(\d{2})\.(\d{2})\.(\d{4})\s*$")
_ITEM_RE = re.compile(r"^[-*]\s+(.+)$")



def bump(version: str) -> str:
    """Return the next explicitly requested patch release."""
    major, minor, patch = (int(x) for x in version.lstrip("v").split("."))
    return "%d.%d.%d" % (major, minor, patch + 1)


def parse(text: str) -> list:
    """Записи файла сверху вниз: [{version, date: "ДД.ММ.ГГГГ", changes: [...]}]."""
    releases = []
    cur = None
    for raw in text.splitlines():
        line = raw.rstrip()
        m = _HEAD_RE.match(line)
        if m:
            cur = {"version": "%s.%s.%s" % m.group(1, 2, 3),
                   "date": "%s.%s.%s" % m.group(4, 5, 6),
                   "changes": []}
            releases.append(cur)
            continue
        if cur is None or not line.strip():
            continue
        if line.startswith("#"):
            # посторонний заголовок закрывает запись: его пункты не её
            cur = None
            continue
        m = _ITEM_RE.match(line.strip())
        if m and not raw[:1].isspace():
            cur["changes"].append(m.group(1).strip())
        elif cur["changes"] and raw[:1].isspace():
            # перенос длинного пункта на следующую строку
            cur["changes"][-1] += " " + line.strip()
    return releases


def load() -> dict:
    """{"version": последняя версия или None, "releases": [...]}.

    Нет файла — пустая история, а не ошибка: без неё программа работает.
    """
    try:
        text = CHANGELOG_FILE.read_text(encoding="utf-8")
    except OSError:
        text = ""
    releases = parse(text)
    return {"version": releases[0]["version"] if releases else None,
            "releases": releases}
