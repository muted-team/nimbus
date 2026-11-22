"""Explicit ordered Cookie fields; selection and identity remain application state."""
from __future__ import annotations

import re

_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,256}", re.ASCII)


def headers_for(pairs, session, expected_transport):
    """Check explicit transport before returning individual HTTP2 Cookie crumbs.

    The underlying curl cookie engine must be cleared at request setup, while
    the Python jar remains caller-owned. This prevents duplicate credentials
    from combining automatic jar cookies with explicit request headers.
    """
    from curl_cffi import requests
    from curl_cffi.const import CurlOpt
    forbidden = {CurlOpt.COOKIE, CurlOpt.COOKIEFILE, CurlOpt.COOKIEJAR,
                 CurlOpt.COOKIESESSION, CurlOpt.HTTPHEADER, CurlOpt.SHARE}
    if (not isinstance(session, requests.Session)
            or session.impersonate != expected_transport["impersonate"]
            or session.default_headers is not False
            or any(session.curl_options.get(key) != value
                   for key, value in expected_transport["curl_options"].items())
            or any(key in session.curl_options for key in forbidden)
            or any(name.lower() == "cookie" for name in session.headers)):
        raise ValueError("Explicit cookies require a matching explicit-cookie Session")
    if not isinstance(pairs, (list, tuple)) or len(pairs) > 64:
        raise ValueError("Expected at most 64 ordered cookie pairs")
    headers = []
    total = 0
    for row in pairs:
        if not isinstance(row, (list, tuple)) or len(row) != 2:
            raise ValueError("Invalid explicit cookie pair")
        name, value = row
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise ValueError("Invalid explicit cookie name")
        if not isinstance(value, str) or len(value) > 16384:
            raise ValueError("Invalid explicit cookie value")
        if any(not (ord(char) == 0x21 or 0x23 <= ord(char) <= 0x2B
                    or 0x2D <= ord(char) <= 0x3A or 0x3C <= ord(char) <= 0x5B
                    or 0x5D <= ord(char) <= 0x7E) for char in value):
            raise ValueError("Invalid explicit cookie value")
        crumb = name + "=" + value
        total += len(crumb)
        if total > 16384:
            raise ValueError("Explicit cookie payload exceeds 16 KiB")
        headers.append(("cookie", crumb))
    return headers
