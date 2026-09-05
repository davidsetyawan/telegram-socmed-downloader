import os
from pathlib import Path

from dotenv import load_dotenv

_ENV_PATH = Path(__file__).parent / ".env"
load_dotenv(_ENV_PATH, override=False)


def _required(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"{name} missing")
    return val


def _optional_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def _optional_str(name: str) -> str | None:
    val = os.environ.get(name)
    return val if val else None


BOT_TOKEN: str = _required("BOT_TOKEN")
ADMIN_ID: int = int(_required("ADMIN_ID"))
ALBUM_MAX: int = _optional_int("ALBUM_MAX", 10)
MAX_FILE_BYTES: int = _optional_int("MAX_FILE_BYTES", 50 * 1024 * 1024)
BASE_URL: str | None = _optional_str("BASE_URL")
