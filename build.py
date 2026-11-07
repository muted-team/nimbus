"""Build the open Nimbus client on the target operating system."""
import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def nuitka_command(target: str, output: Path) -> list[str]:
    command = [sys.executable, "-m", "nuitka", "--standalone", "--enable-plugin=pywebview",
               "--assume-yes-for-downloads", "--remove-output",
               "--output-dir=" + str(output),
               "--output-filename=" + ("Nimbus.exe" if target == "win32" else "Nimbus"),
               "--include-data-dir=ui=ui", "--include-data-file=CHANGELOG.md=CHANGELOG.md",
               "--include-data-file=modules/ca.pem=modules/ca.pem",
               "--include-data-file=LICENSE=LICENSE",
               "--include-data-file=THIRD_PARTY_NOTICES.md=THIRD_PARTY_NOTICES.md"]
    if target == "win32":
        command += ["--windows-console-mode=disable", "--windows-icon-from-ico=app.ico"]
    if target == "darwin":
        command += ["--macos-create-app-bundle", "--macos-app-name=Nimbus"]
    # Each package carries the toolkit used on its target OS.
    unwanted = {"win32": ("android", "cocoa", "gtk", "qt"),
                "linux": ("android", "cocoa", "winforms", "edgechromium"),
                "darwin": ("android", "gtk", "qt", "winforms", "edgechromium")}
    command += ["--nofollow-import-to=webview.platforms." + name for name in unwanted.get(target, ())]
    command += ["--nofollow-import-to=playwright", "--nofollow-import-to=server",
                "--nofollow-import-to=tests", str(ROOT / "app.py")]
    return command


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-frontend", action="store_true")
    args = parser.parse_args()
    from modules import changelog
    version = changelog.load()["version"]
    if not version:
        raise SystemExit("CHANGELOG.md has no release version")
    target = "linux" if sys.platform.startswith("linux") else sys.platform
    output = ROOT / "build" / (target + "-" + platform.machine())
    command = nuitka_command(target, output)
    if args.dry_run:
        print(" ".join(command))
        return 0
    if not args.skip_frontend:
        npm = shutil.which("npm.cmd" if target == "win32" else "npm")
        if not npm:
            raise SystemExit("Node.js/npm is required to build the interface")
        for step in ((npm, "ci"), (npm, "run", "build:app")):
            subprocess.run(step, cwd=ROOT / "web", check=True)
    if not (ROOT / "ui" / "index.html").is_file():
        raise SystemExit("Build the interface first: npm run build:app")
    output.mkdir(parents=True, exist_ok=True)
    if (output / "app.dist").exists() or (output / "app.app").exists():
        raise SystemExit("Build output already exists; use a clean checkout for a release")
    subprocess.run(command, cwd=ROOT, check=True)
    built = output / ("app.app" if target == "darwin" else "app.dist")
    destination = output / ("Nimbus.app" if target == "darwin" else "Nimbus v" + version)
    built.rename(destination)
    archive = ROOT / "dist" / ("nimbus-" + version + "-" + target + "-" + platform.machine())
    archive.parent.mkdir(exist_ok=True)
    shutil.make_archive(str(archive), "zip", root_dir=destination.parent, base_dir=destination.name)
    print("Built " + str(archive) + ".zip")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
