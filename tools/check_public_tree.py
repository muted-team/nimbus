"""Reject private service code and user data from the distributable client tree."""
import ast
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BLOCKED_MODULES = {"server", "signing", "signers", "ticket_guard", "login", "totp", "mailcode",
                   "set_account", "session_manager", "device", "profile_fetch", "publish",
                   "tos_upload", "video_upload", "studio", "delete_post", "api", "waf", "anon"}
PRIVATE_NAMES = {"config.json", "accounts.json", "banned.json", "data.db", "ts_guard_config.json",
                 "state.key", "keys.txt", "AGENTS.md"}


def violations(files: list[Path]) -> list[str]:
    errors = []
    for path in files:
        relative = path.relative_to(ROOT)
        if (path.name in PRIVATE_NAMES or relative.parts[0] in ("server", "sessions", "logs", "media", "assets")
                or path.suffix.lower() in (".har", ".jar", ".key", ".state")):
            errors.append(str(relative) + ": private file")
        if path.suffix not in (".py", ".json", ".ts", ".tsx", ".js", ".mjs", ".md", ".txt", ".pem"):
            continue
        text = path.read_text(errors="replace")
        if re.search(r"-----BEGIN (?:EC |RSA |OPENSSH )?PRIVATE KEY-----", text):
            errors.append(str(relative) + ": private key")
        if re.search(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b", text):
            errors.append(str(relative) + ": access token")
        if path.suffix == ".py" and relative.parts[0] == "modules":
            if path.stem in BLOCKED_MODULES:
                errors.append(str(relative) + ": service module")
            for node in ast.walk(ast.parse(text)):
                if not isinstance(node, ast.ImportFrom):
                    continue
                if node.level:
                    names = [(node.module or "").split(".")[0]] + [a.name for a in node.names]
                elif (node.module or "").startswith("modules."):
                    names = [(node.module or "").split(".")[1]]
                else:
                    continue
                for name in names:
                    if name in BLOCKED_MODULES:
                        errors.append(f"{relative}:{node.lineno}: imports private module {name}")
    return errors


def main() -> int:
    result = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                            cwd=ROOT, check=True, capture_output=True)
    files = [ROOT / name.decode() for name in result.stdout.split(b"\0") if name]
    errors = violations([p for p in files if p.is_file()])
    for error in errors:
        print(error)
    print(f"Public source check: {len(files)} files, {len(errors)} errors")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
