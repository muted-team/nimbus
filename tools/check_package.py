"""Check release archives for source files, private data and missing UI."""
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = {"AGENTS.md", "config.json", "accounts.json", "banned.json", "state.key", "keys.txt"}


def check(path: Path) -> list[str]:
    errors = []
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if not any(name.endswith("ui/index.html") for name in names):
            errors.append("Interface is missing")
        if not any(name.endswith(("/Nimbus.exe", "/Nimbus")) for name in names):
            errors.append("Application executable is missing")
        for name in names:
            parts = Path(name).parts
            if (Path(name).name in PRIVATE or any(p in ("tests", "server", "sessions", ".git", ".venv") for p in parts)
                    or name.endswith((".har", ".jar", ".state", ".py", ".tsx", ".ts"))):
                errors.append("Unexpected file: " + name)
    return errors


def main() -> int:
    packages = list((ROOT / "dist").glob("*.zip"))
    if not packages:
        raise SystemExit("No release archive found")
    failed = False
    for package in packages:
        errors = check(package)
        print(package.name + ": " + ("OK" if not errors else "; ".join(errors)))
        failed = failed or bool(errors)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
