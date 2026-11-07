"""Use UTF-8 diagnostics without depending on the system console code page."""
import sys


def configure_console(streams=None) -> None:
    for stream in streams if streams is not None else (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
        except (OSError, ValueError):
            pass
