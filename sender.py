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


_POST_RE = re.compile(
    r"^https?://(?:www\.)?(?:instagram\.com/(?:p|reel)/[\w-]+/?|"
    r"(?:twitter|x)\.com/[^/]+/status/\d+/?)$",
    re.IGNORECASE,
)


def _url_kind(url: str) -> str:
    return "post" if _POST_RE.match(url.strip()) else "profile"


def _username_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return None
    name = parts[0].split("?")[0]
    if re.match(r"^[A-Za-z0-9._-]+$", name):
        return name
    return None


def _kwdict_username(kw: dict) -> str | None:
    """Username/handle from a gallery-dl kwdict.

    Order: Instagram `username`, Twitter `user.name`, generic `uploader`.
    """
    username = kw.get("username")
    if username:
        return str(username)
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
    """Display name from a gallery-dl kwdict.

    Order: Instagram `fullname`, Twitter `user.nick`.
    """
    fullname = kw.get("fullname")
    if fullname:
        return str(fullname)
    user = kw.get("user") or {}
    if isinstance(user, dict):
        nick = user.get("nick")
        if nick:
            return str(nick)
    return None


def _kwdict_content(kw: dict) -> str | None:
    """Post text from a gallery-dl kwdict.

    Order: Instagram `description`, then generic `content`.
    """
    for k in ("description", "content"):
        v = kw.get(k)
        if v and isinstance(v, str):
            return v
    return None


def _kwdict_post_url(kw: dict, fallback_url: str) -> str:
    return str(kw.get("post_url") or fallback_url)


def _truncate_caption(text: str, limit: int = 1024) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _profile_url(handle: str, host_hint: str) -> str:
    if "instagram.com" in host_hint:
        return f"https://www.instagram.com/{handle}/"
    if "twitter.com" in host_hint:
        return f"https://twitter.com/{handle}"
    return f"https://x.com/{handle}"


def _html_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _parse_mode_for(caption: str | None) -> str | None:
    if caption and "<" in caption:
        return "HTML"
    return None


def build_caption(
    url: str, kwdicts: list[dict], files: list[Path]
) -> str | None:
    """Build a caption for the first file in the album.

    Post URL (HTML):
        <post text>

        By: <a href="<profile url>">@<handle></a> (<display name>)
        <post url>

    Profile URL (HTML):
        From: <a href="<profile url>">@<handle></a> (<display name>)
        <profile url>
    """
    if not files:
        return None
    kind = _url_kind(url)
    first_kw = kwdicts[0] if kwdicts else {}
    display = _kwdict_display(first_kw)
    handle = _kwdict_username(first_kw)
    if not handle and kind == "profile":
        # Profile URL has the username as path[0]. Safe to parse.
        handle = _username_from_url(url)
    host_hint = urlparse(url).hostname or ""
    if handle:
        profile_url = _profile_url(handle, host_hint)
        handle_link = f'<a href="{_html_escape(profile_url)}">@{_html_escape(handle)}</a>'
    else:
        handle_link = "unknown"
    if kind == "post":
        content = (_kwdict_content(first_kw) or "").strip()
        post_url = _kwdict_post_url(first_kw, url)
        byline = f"By: {handle_link}"
        if display:
            byline += f" ({_html_escape(display)})"
        body = "\n\n".join(
            part for part in (_html_escape(content), byline, _html_escape(post_url)) if part
        )
    else:
        line1 = f"From: {handle_link}"
        if display:
            line1 += f" ({_html_escape(display)})"
        body = f"{line1}\n{_html_escape(url)}"
    return _truncate_caption(body)


async def _send_image(bot: Bot, chat_id: int, f: Path, caption: str | None) -> None:
    with open(f, "rb") as fh:
        data = fh.read()
    await bot.send_photo(
        chat_id=chat_id, photo=data, filename=f.name, caption=caption,
        parse_mode=_parse_mode_for(caption),
    )


async def _send_video(bot: Bot, chat_id: int, f: Path, caption: str | None) -> None:
    with open(f, "rb") as fh:
        data = fh.read()
    await bot.send_video(
        chat_id=chat_id, video=data, filename=f.name, caption=caption,
        supports_streaming=True,
        parse_mode=_parse_mode_for(caption),
    )


async def _send_doc(bot: Bot, chat_id: int, f: Path, caption: str | None) -> None:
    with open(f, "rb") as fh:
        data = fh.read()
    await bot.send_document(
        chat_id=chat_id, document=data, filename=f.name, caption=caption,
        parse_mode=_parse_mode_for(caption),
    )


async def _send_image_album(
    bot: Bot, chat_id: int, chunk: list[Path], caption: str | None
) -> None:
    media = []
    for idx, f in enumerate(chunk):
        with open(f, "rb") as fh:
            data = fh.read()
        item_caption = caption if idx == 0 else None
        media.append(
            InputMediaPhoto(
                media=data, filename=f.name, caption=item_caption,
                parse_mode=_parse_mode_for(item_caption),
            )
        )
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
