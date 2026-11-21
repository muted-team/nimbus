"""Opaque browser states, isolated from HTTP sessions and from other modes."""

import hashlib
import os
from pathlib import Path
import tempfile


class BrowserStates:
    def __init__(self, root, namespace):
        self.root = Path(root) / hashlib.sha256(namespace.encode()).hexdigest()

    def path(self, username, mode):
        if type(mode) is not int or mode not in (3, 4):
            raise ValueError("Browser state requires mode 3 or 4")
        if not isinstance(username, str) or not username.strip():
            raise ValueError("Username is required")
        account = hashlib.sha256(username.encode()).hexdigest()
        return self.root / str(mode) / (account + ".state")

    def read(self, username, mode):
        path = self.path(username, mode)
        return path.read_text(encoding="utf-8") if path.exists() else None

    def write(self, username, mode, state):
        if not isinstance(state, str) or not state.strip():
            raise ValueError("A confirmed opaque browser state is required")
        path = self.path(username, mode)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                             prefix=".pending-", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(state)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def clear_confirmed(self, username, mode, response):
        """Only a confirmed logout can delete this exact browser namespace."""
        if (isinstance(response, dict) and response.get("ok") is True
                and response.get("confirmed") is True):
            self.path(username, mode).unlink(missing_ok=True)
            return True
        return False
