"""Immutable metadata for explicitly measured project profiles."""
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProfileInfo:
    name: str
    firefox_major: int
    baseline: str
    curl_cffi_version: str
    camoufox_version: str
    browser_version: str
    measured_at: str
    scope: tuple[str, ...]
