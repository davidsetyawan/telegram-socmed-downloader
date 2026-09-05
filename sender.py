import mimetypes
import re
from pathlib import Path
from urllib.parse import urlparse

from telegram import Bot, InputMediaPhoto, InputMediaVideo

import config


def _category(p: Path) -> str:
    mime, _ = mimetypes.guess_type(str(p), strict=False)
    if mime is None:
        return "application"
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    return "application"


def _chunks(items: list, n: int):
    for i in range(0, len(items), n):
        yield items[i : i + n]


# Matches a post-style URL: instagram /p/... or /reel/..., twitter /status/...
_POST_RE = re.compile(
    r"^https?://(?:www\.)?(?:instagram\.com/(?:p|reel)/[\w-]+/?|"
    r"(?:twitter|x)\.com/[^/]+/status/\d+/?)$",
    re.IGNORECASE,
)


def _url_kind(url: str) -> str:
    """Return 'post' if the URL is a single-post URL, else 'profile'."""
    return "post" if _POST_RE.match(url.strip()) else "profile"


def _username_from_url(url: str) -> str | None:
    """Extract the username from a profile URL.

    https://www.instagram.com/username/ -> 'username'
    https://twitter.com/username         -> 'username'
    """
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return None
    # IG: first path segment after host; Twitter: same.
    name = parts[0]
    # Strip trailing slash artifacts; keep alnum + underscore + period.
    name = name.split("?")[0]
    if re.match(r"^[A-Za-z0-9._-]+$", name):
        return name
    return None


def _kwdict_username(kw: dict) -> str | None:
    """Pull a username/handle from a gallery-dl kwdict if present."""
    user = kw.get("user") or {}
    if isinstance(user, dict):
        name = user.get("name")
        if name:
            return str(name)
    uploader = kw.get("uploader")
    if uploader:
        return str(uploader)
    return None


def _kwdict_display(kw: dict) -> str | None:
    """Pull a display name from a gallery-dl kwdict if present.

    Twitter puts a 'nick' on user; IG's uploader_id is not a display name.
    """
    user = kw.get("user") or {}
    if isinstance(user, dict):
        nick = user.get("nick")
        if nick:
            return str(nick)
    return None


def _kwdict_content(kw: dict) -> str | None:
    content = kw.get("content")
    if content and isinstance(content, str):
        return content
    return None


def _kwdict_post_url(kw: dict, fallback_url: str) -> str:
    return str(kw.get("post_url") or fallback_url)


def _truncate_caption(text: str, limit: int = 1024) -> str:
    """Telegram caption limit is 1024 chars; trim and add ellipsis if needed."""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def build_caption(
    url: str, kwdicts: list[dict], files: list[Path]
) -> str | None:
    """Build a caption for the first file in the album.

    Profile URL: '@<handle> (<display name>)\\n<profile url>'
    Post URL:    '<post text>\\n\\nBy: @<handle> (<display name>)\\n<post url>'

    Returns None if no caption is possible (e.g. no handle found).
    """
    if not files:
        return None
    kind = _url_kind(url)
    first_kw = kwdicts[0] if kwdicts else {}
    handle = _kwdict_username(first_kw) or _username_from_url(url)
    display = _kwdict_display(first_kw)
    if kind == "post":
        content = (_kwdict_content(first_kw) or "").strip()
        post_url = _kwdict_post_url(first_kw, url)
        byline = f"By: @{handle}" if handle else "By: unknown"
        if display:
            byline += f" ({display})"
        body = "\n\n".join(part for part in (content, byline, post_url) if part)
    else:
        # Profile: '@<handle> (<display name>)\\n<profile url>'
        line1 = f"@{handle}" if handle else "@unknown"
        if display:
            line1 += f" ({display})"
        body = f"{line1}\n{url}"
    return _truncate_caption(body)


async def _send_image(bot: Bot, chat_id: int, f: Path, caption: str | None) -> None:
    with open(f, "rb") as fh:
        data = fh.read()
    await bot.send_photo(chat_id=chat_id, photo=data, filename=f.name, caption=caption)


async def _send_video(bot: Bot, chat_id: int, f: Path, caption: str | None) -> None:
    with open(f, "rb") as fh:
        data = fh.read()
    await bot.send_video(
        chat_id=chat_id, video=data, filename=f.name, caption=caption, supports_streaming=True
    )


async def _send_doc(bot: Bot, chat_id: int, f: Path, caption: str | None) -> None:
    with open(f, "rb") as fh:
        data = fh.read()
    await bot.send_document(chat_id=chat_id, document=data, filename=f.name, caption=caption)


async def _send_image_album(
    bot: Bot, chat_id: int, chunk: list[Path], caption: str | None
) -> None:
    media = []
    for idx, f in enumerate(chunk):
        with open(f, "rb") as fh:
            data = fh.read()
        item_caption = caption if idx == 0 else None
        media.append(InputMediaPhoto(media=data, filename=f.name, caption=item_caption))
    await bot.send_media_group(chat_id=chat_id, media=media)


async def send_files(
    bot: Bot,
    chat_id: int,
    files: list[Path],
    caption: str | None,
) -> None:
    files = sorted(files, key=lambda p: str(p))
    big = [f for f in files if f.stat().st_size > config.MAX_FILE_BYTES]
    small = [f for f in files if f.stat().st_size <= config.MAX_FILE_BYTES]

    if big:
        names = ", ".join(f.name for f in big)
        await bot.send_message(chat_id=chat_id, text=f"skipped (>50MB): {names}")

    if not small:
        return

    images = [f for f in small if _category(f) == "image"]
    videos = [f for f in small if _category(f) == "video"]
    docs = [f for f in small if _category(f) == "application"]

    first_caption_used = False

    for chunk in _chunks(images, config.ALBUM_MAX):
        cap = caption if not first_caption_used else None
        if len(chunk) == 1:
            await _send_image(bot, chat_id, chunk[0], cap)
        else:
            await _send_image_album(bot, chat_id, chunk, cap)
        first_caption_used = True

    for f in videos:
        cap = caption if not first_caption_used else None
        await _send_video(bot, chat_id, f, cap)
        first_caption_used = True

    for f in docs:
        cap = caption if not first_caption_used else None
        await _send_doc(bot, chat_id, f, cap)
        first_caption_used = True
