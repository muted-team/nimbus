"""Version-pinned Camoufox158 transport profile; see docs/impersonation.md.

The reference is Camoufox0.5.9 / Firefox158.0.1-beta.41 on fresh TLS1.3/h2
connections. Application cookies, request context and JavaScript remain caller
state. This module never reads configuration, registers global curl aliases,
changes trust settings or performs a request.
"""
from __future__ import annotations

import importlib.metadata
import re

from curl_cffi.const import CurlOpt

from ._reference158 import DEFAULT_HEADERS
from ._types import ProfileInfo

INFO = ProfileInfo(
    name="camoufox158", firefox_major=158, baseline="firefox155",
    curl_cffi_version="0.17.0", camoufox_version="0.5.9",
    browser_version="158.0.1-beta.41", measured_at="2026-11-10",
    scope=("fresh TLS1.3", "HTTP2", "navigation", "fetch-get", "fetch-post", "explicit HTTP2 Cookie fields"),
)
SUPPORTED_GROUPS = "X25519MLKEM768:X25519:P-256:P-384:P-521"
_PUBLIC_VALUES = frozenset({
    "user-agent", "accept", "accept-language", "accept-encoding",
    "upgrade-insecure-requests", "sec-fetch-dest", "sec-fetch-mode",
    "sec-fetch-site", "sec-fetch-user", "priority", "te", "content-type",
})
_PSEUDO = {":method": "m", ":path": "p", ":authority": "a", ":scheme": "s"}
_TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,256}", re.ASCII)


def _runtime_version() -> str:
    return importlib.metadata.version("curl_cffi")


def _validate_ua(value: str) -> None:
    firefox = re.findall(r"Firefox/(\d+)(?:\.\d+)*(?=$|[\s;)])", value)
    gecko = re.findall(r"rv:(\d+)(?:\.\d+)*(?=$|[\s;)])", value)
    if (firefox != [str(INFO.firefox_major)] or gecko != [str(INFO.firefox_major)]
            or re.search(r"Chrome/|Chromium/", value, re.I)):
        raise ValueError("User-Agent must identify the measured Firefox158 engine")


def kwargs_for(sampletype: str, observed_headers=None) -> dict:
    """Return independent Session kwargs for a measured request class.

    Without observed_headers, use the checked synthetic Windows reference.
    Observed headers must be ordered HTTP2 request pairs, with four unique
    pseudo headers before regular fields. Request-specific values are filtered.
    Every field is validated, including ignored fields; errors never echo input.
    """
    if not isinstance(sampletype, str) or sampletype not in DEFAULT_HEADERS:
        raise ValueError("Unknown measured scenario")
    if _runtime_version() != INFO.curl_cffi_version:
        raise RuntimeError("camoufox158 requires revalidation with this curl_cffi version")
    rows = DEFAULT_HEADERS[sampletype] if observed_headers is None else observed_headers
    if not isinstance(rows, (list, tuple)) or not 1 <= len(rows) <= 100:
        raise ValueError("Expected 1 to 100 ordered header pairs")
    headers, order, pseudo, seen = [], [], [], set()
    regular_started = False
    last_regular = None
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) != 2:
            raise ValueError("Invalid observed header pair")
        original_name, value = row
        if not isinstance(original_name, str) or not 1 <= len(original_name) <= 256:
            raise ValueError("Invalid observed header name")
        if original_name.startswith(":"):
            valid_name = original_name in _PSEUDO
        else:
            valid_name = _TOKEN.fullmatch(original_name) is not None
        if not valid_name:
            raise ValueError("Invalid observed header name")
        name = original_name.lower()
        if name in seen and name != "cookie":
            raise ValueError("Duplicate observed header name")
        if name == "cookie" and name in seen and last_regular != "cookie":
            raise ValueError("Observed HTTP2 Cookie fields must be contiguous")
        seen.add(name)
        if not isinstance(value, str) or len(value) > 16384:
            raise ValueError("Invalid observed header value")
        try:
            valid = len(value.encode("utf-8")) <= 16384
        except UnicodeEncodeError:
            valid = False
        if not valid or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Invalid observed header value")
        if name in _PSEUDO:
            if regular_started:
                raise ValueError("HTTP2 pseudo headers must precede regular fields")
            pseudo.append(_PSEUDO[name])
            continue
        regular_started = True
        last_regular = name
        # Order is a transport property, including caller-owned fields. Their
        # values remain excluded below. Preserve every validated field name.
        if name not in order:
            order.append(name)
        if name in _PUBLIC_VALUES:
            if name == "user-agent":
                _validate_ua(value)
            headers.append((name, value))
    if len(pseudo) != 4 or set(pseudo) != {"m", "p", "a", "s"}:
        raise ValueError("Expected four unique HTTP2 pseudo headers")
    if "user-agent" not in seen:
        raise ValueError("Observed native User-Agent is required")
    if "cookie" not in seen:
        # Native Firefox emits cookie crumbs before navigation/fetch metadata.
        # An ordering slot does not create a header when the request has none.
        anchor = next((name for name in ("upgrade-insecure-requests", "sec-fetch-dest") if name in order), None)
        order.insert(order.index(anchor) if anchor else len(order), "cookie")
    return {
        "impersonate": INFO.baseline,
        "default_headers": False,
        "headers": headers,
        "extra_fp": {
            "http2_stream_weight": 42 if sampletype == "navigation" else 22,
            "http2_stream_exclusive": 0,
            "header_order": ",".join(order),
        },
        "curl_options": {
            CurlOpt.SSL_EC_CURVES: SUPPORTED_GROUPS,
            CurlOpt.HTTP2_PSEUDO_HEADERS_ORDER: "".join(pseudo),
        },
    }
