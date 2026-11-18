"""Check release archives for source files, private data and missing UI."""
import json
import re
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
        pointers = [name for name in names if name.endswith('/.nimbus-current')]
        if not any(name.endswith('.app/Contents/MacOS/Nimbus') for name in names):
            if len(pointers) != 1:
                errors.append("Exactly one runtime pointer is required")
            else:
                pointer = pointers[0]
                prefix = pointer.removesuffix('.nimbus-current')
                try:
                    runtime = archive.read(pointer).decode('ascii').removesuffix('\n')
                    if not re.fullmatch(r'runtime-v\d+\.\d+\.\d+', runtime):
                        raise ValueError('Invalid runtime pointer')
                    marker = json.loads(archive.read(prefix + '.nimbus-bootstrap.json'))
                    runtime_prefix = prefix + 'runtimes/' + runtime + '/'
                    runtime_marker = json.loads(archive.read(runtime_prefix + '.nimbus-runtime.json'))
                    if marker != {'format': 1} or runtime_marker != {'format': 1, 'version': runtime.removeprefix('runtime-v')}:
                        raise ValueError('Invalid bootstrap metadata')
                    if prefix + 'Nimbus.exe' not in names and prefix + 'Nimbus' not in names:
                        raise ValueError('Stable launcher is missing')
                    binary = 'Nimbus-runtime.exe' if prefix + 'Nimbus.exe' in names else 'Nimbus-runtime'
                    if runtime_prefix + binary not in names or runtime_prefix + 'ui/index.html' not in names:
                        raise ValueError('Selected runtime is incomplete')
                except (KeyError, ValueError, UnicodeError, TypeError):
                    errors.append("Selected runtime or bootstrap metadata is invalid")
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
