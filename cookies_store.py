import os

from pathlib import Path
from urllib.parse import urlparse

from paths import DATA_DIR

_IG_PATH = DATA_DIR / "cookies_instagram.txt"
_TW_PATH = DATA_DIR / "cookies_twitter.txt"
_VALID_HEADERS = (
    "# Netscape HTTP Cookie File",
    "# HTTP Cookie File",
)
_IG_PATTERNS = ("instagram",)
_TW_PATTERNS = ("twitter", "x.com")


class CookieError(ValueError):
    pass


def _host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _bucket_for_host(url: str) -> str | None:
    host = _host_of(url)
    if "instagram.com" in host:
        return "instagram"
    if "twitter.com" in host or host == "x.com" or host.endswith(".x.com"):
        return "twitter"
    return None


def get_path_for_host(url: str) -> Path | None:
    bucket = _bucket_for_host(url)
    if bucket is None:
        return None
    p = _IG_PATH if bucket == "instagram" else _TW_PATH
    if p.exists() and p.stat().st_size > 0:
        return p
    return None


def bucket_name_for_filename(filename: str) -> str:
    """Classify an uploaded filename to instagram/twitter/ambiguous/none.

    Case-insensitive substring match. If the filename mentions both an
    instagram pattern AND a twitter pattern, it's ambiguous and rejected.
    """
    name = filename.lower()
    has_ig = any(pat in name for pat in _IG_PATTERNS)
    has_tw = any(pat in name for pat in _TW_PATTERNS)
    if has_ig and has_tw:
        raise CookieError(
            "filename matches both instagram and twitter; rename the file"
        )
    if has_ig:
        return "instagram"
    if has_tw:
        return "twitter"
    raise CookieError(
        "filename must contain 'instagram', 'twitter', or 'x.com' (e.g. "
        "www.instagram.com_cookies.txt or x.com_cookies.txt)"
    )


def save_for_bucket(upload_bytes: bytes, bucket: str) -> Path:
    if bucket not in ("instagram", "twitter"):
        raise CookieError(f"unknown bucket: {bucket}")
    text = upload_bytes.decode("utf-8", errors="replace").lstrip()
    first_line = text.splitlines()[0] if text else ""
    if first_line not in _VALID_HEADERS:
        raise CookieError("invalid cookies file format")
    target = _IG_PATH if bucket == "instagram" else _TW_PATH
    tmp = target.with_suffix(".txt.tmp")
    with open(tmp, "wb") as f:
        f.write(upload_bytes)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, target)
    return target
