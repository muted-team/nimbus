"""Project-owned curl_cffi profiles: camoufox158 and latest-checked camoufox.

Use kwargs_for(..., profile="camoufox158") to pin a profile, or "camoufox"
to follow the latest explicitly registered and verified profile. These names
belong to this registry, not curl_cffi's built-in impersonate strings.
See docs/impersonation.md before modifying profiles or advancing an alias.
"""
from types import MappingProxyType

from . import camoufox158
from ._types import ProfileInfo

_PROFILES = MappingProxyType({"camoufox158": camoufox158})
LATEST_PROFILE = max(_PROFILES, key=lambda name: _PROFILES[name].INFO.firefox_major)
ALIASES = MappingProxyType({"camoufox": LATEST_PROFILE})


def available_profiles() -> tuple[str, ...]:
    return tuple(ALIASES) + tuple(_PROFILES)


def _resolve(name):
    if not isinstance(name, str):
        raise ValueError("Unknown impersonation profile; choose a registered name")
    resolved = ALIASES.get(name, name)
    if resolved not in _PROFILES:
        raise ValueError("Unknown impersonation profile; choose a registered name")
    return _PROFILES[resolved]


def get_profile(name: str = "camoufox") -> ProfileInfo:
    return _resolve(name).INFO


def kwargs_for(sampletype, observed_headers=None, *, profile="camoufox") -> dict:
    return _resolve(profile).kwargs_for(sampletype, observed_headers)


def session_kwargs(profile="camoufox", *, cookie_mode="jar") -> dict:
    """Common transport; explicit mode suppresses curl-handle jar emission only.

    The default jar mode retains curl cookie semantics. To reproduce ordered
    native Cookie fields, opt into explicit and pass selected cookie_pairs to
    request_kwargs together with the actual Session. Python jar state is owned
    by the application and is not mutated by these factories.
    """
    if not isinstance(cookie_mode, str) or cookie_mode not in {"jar", "explicit"}:
        raise ValueError("Unknown cookie mode; choose jar or explicit")
    options = kwargs_for("navigation", profile=profile)
    if cookie_mode == "explicit":
        from curl_cffi.const import CurlOpt
        options["curl_options"][CurlOpt.COOKIELIST] = "ALL"
    return {"impersonate": options["impersonate"], "default_headers": False,
            "headers": {}, "curl_options": options["curl_options"]}


def request_kwargs(sampletype, observed_headers=None, *, profile="camoufox", cookie_pairs=None, session=None) -> dict:
    """Per-call headers/priority/decoder, without leaking navigation defaults.

    Pair this with session_kwargs() for mixed requests on one cookie-owning
    Session. A caller-supplied pseudo order differing from the fixed transport
    requires a separately constructed Session through kwargs_for(). Explicit
    cookie_pairs require a verified explicit Session and disable redirects;
    the caller must select cookies again for each next origin/path.
    """
    options = kwargs_for(sampletype, observed_headers, profile=profile)
    transport = session_kwargs(profile)
    if options["curl_options"] != transport["curl_options"]:
        raise ValueError("Observed pseudo-header order differs from reusable session transport")
    encoding = dict(options["headers"]).get("accept-encoding")
    if not encoding:
        raise ValueError("Observed Accept-Encoding is required for request options")
    result = {"headers": options["headers"], "extra_fp": options["extra_fp"],
              "accept_encoding": encoding}
    if cookie_pairs is not None:
        from ._cookies import headers_for
        result["headers"].extend(headers_for(cookie_pairs, session, session_kwargs(profile, cookie_mode="explicit")))
        # Explicit values are scoped to this request. A redirect requires the
        # caller to reselect cookies for the next origin/path.
        result["allow_redirects"] = False
    return result


__all__ = ("ALIASES", "LATEST_PROFILE", "ProfileInfo", "available_profiles", "get_profile",
           "kwargs_for", "session_kwargs", "request_kwargs")
