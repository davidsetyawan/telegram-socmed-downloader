import os
from pathlib import Path
from urllib.parse import urlparse

from paths import DATA_DIR

_IG_PATH = DATA_DIR / "cookies_instagram.txt"
_TW_PATH = DATA_DIR / "cookies_twitter.txt"
_PATHS = {"instagram": _IG_PATH, "twitter": _TW_PATH}
_VALID_HEADERS = ("# Netscape HTTP Cookie File", "# HTTP Cookie File")


class CookieError(ValueError):
    pass


def _host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def bucket_for_host(url: str) -> str | None:
    """Classify a URL to 'instagram', 'twitter', or None."""
    host = _host_of(url)
    if "instagram.com" in host:
        return "instagram"
    if "twitter.com" in host or host == "x.com" or host.endswith(".x.com"):
        return "twitter"
    return None


def get_path_for_host(url: str) -> Path | None:
    bucket = bucket_for_host(url)
    if bucket is None:
        return None
    p = _PATHS[bucket]
    if p.exists() and p.stat().st_size > 0:
        return p
    return None


def bucket_name_for_filename(filename: str) -> str:
    """Classify an uploaded filename to instagram/twitter or raise CookieError.

    Case-insensitive substring match. A filename mentioning both instagram and
    twitter/x.com is rejected as ambiguous.
    """
    name = filename.lower()
    has_ig = "instagram" in name
    has_tw = "twitter" in name or "x.com" in name
    if has_ig and has_tw:
        raise CookieError("filename matches both instagram and twitter; rename the file")
    if has_ig:
        return "instagram"
    if has_tw:
        return "twitter"
    raise CookieError(
        "filename must contain 'instagram', 'twitter', or 'x.com' "
        "(e.g. www.instagram.com_cookies.txt or x.com_cookies.txt)"
    )


def save_for_bucket(upload_bytes: bytes, bucket: str) -> Path:
    if bucket not in _PATHS:
        raise CookieError(f"unknown bucket: {bucket}")
    first_line = upload_bytes.decode("utf-8", errors="replace").lstrip().splitlines()[:1]
    if not first_line or first_line[0] not in _VALID_HEADERS:
        raise CookieError("invalid cookies file format")
    target = _PATHS[bucket]
    tmp = target.with_suffix(".txt.tmp")
    with open(tmp, "wb") as f:
        f.write(upload_bytes)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, target)
    return target
