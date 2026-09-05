import json
import logging
import os
from pathlib import Path

from paths import DATA_DIR

_WHITELIST_PATH = DATA_DIR / "whitelist.json"
_log = logging.getLogger(__name__)


def _path() -> Path:
    return _WHITELIST_PATH


def load() -> set[int]:
    p = _path()
    if not p.exists():
        return set()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        _log.exception("whitelist file corrupt; treating as empty: %s", p)
        return set()
    ids = data.get("user_ids", [])
    out: set[int] = set()
    for item in ids:
        try:
            out.add(int(item))
        except (TypeError, ValueError):
            continue
    return out


def save(ids: set[int]) -> None:
    p = _path()
    tmp = p.with_suffix(".json.tmp")
    payload = {"user_ids": sorted(ids)}
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def is_allowed(user_id: int) -> bool:
    return user_id in load()


def add(user_id: int) -> None:
    ids = load()
    ids.add(int(user_id))
    save(ids)


def remove(user_id: int) -> None:
    ids = load()
    ids.discard(int(user_id))
    save(ids)
