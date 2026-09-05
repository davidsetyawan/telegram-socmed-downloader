import mimetypes
from pathlib import Path
from urllib.parse import urlparse

from telegram import Bot, InputMediaPhoto, InputMediaVideo

import config
import cookies_store

ALBUM_MAX = 10
CAPTION_LIMIT = 1024


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


def _truncate(text: str) -> str:
    if len(text) <= CAPTION_LIMIT:
        return text
    return text[: CAPTION_LIMIT - 1].rstrip() + "…"


def _html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _parse_mode_for(caption: str | None) -> str | None:
    return "HTML" if caption and "<" in caption else None


def _handle_from_kw(kw: dict) -> str | None:
    if (u := kw.get("username")):
        return str(u)
    user = kw.get("user") or {}
    if isinstance(user, dict) and (n := user.get("name")):
        return str(n)
    if (u := kw.get("uploader")):
        return str(u)
    return None


def _display_from_kw(kw: dict) -> str | None:
    if (f := kw.get("fullname")):
        return str(f)
    user = kw.get("user") or {}
    if isinstance(user, dict) and (n := user.get("nick")):
        return str(n)
    return None


def _is_post(url: str) -> bool:
    return "/p/" in url or "/reel/" in url or "/status/" in url


def build_caption(url: str, kwdicts: list[dict], files: list[Path]) -> str | None:
    """Build an HTML caption for the first file. See README for shape."""
    if not files:
        return None
    kw = kwdicts[0] if kwdicts else {}
    handle = _handle_from_kw(kw)
    if not handle and not _is_post(url):
        parts = urlparse(url).path.strip("/").split("/")
        if parts and parts[0]:
            handle = parts[0]
    display = _display_from_kw(kw)
    bucket = cookies_store.bucket_for_host(url) or ""
    if handle:
        host = "www.instagram.com" if bucket == "instagram" else "x.com"
        profile = f"https://{host}/{handle}"
        handle_link = f'<a href="{_html(profile)}">@{_html(handle)}</a>'
    else:
        handle_link = "unknown"
    byline = f"{'By' if _is_post(url) else 'From'}: {handle_link}"
    if display:
        byline += f" ({_html(display)})"
    if _is_post(url):
        content = (kw.get("description") or kw.get("content") or "").strip()
        post_url = str(kw.get("post_url") or url)
        body = "\n\n".join(p for p in (_html(content), byline, _html(post_url)) if p)
    else:
        body = f"{byline}\n{_html(url)}"
    return _truncate(body)


async def _read(f: Path) -> bytes:
    with open(f, "rb") as fh:
        return fh.read()


async def _send_photo(bot: Bot, chat_id: int, f: Path, caption: str | None) -> None:
    await bot.send_photo(
        chat_id=chat_id,
        photo=await _read(f),
        filename=f.name,
        caption=caption,
        parse_mode=_parse_mode_for(caption),
    )


async def _send_video(bot: Bot, chat_id: int, f: Path, caption: str | None) -> None:
    await bot.send_video(
        chat_id=chat_id,
        video=await _read(f),
        filename=f.name,
        caption=caption,
        supports_streaming=True,
        parse_mode=_parse_mode_for(caption),
    )


async def _send_doc(bot: Bot, chat_id: int, f: Path, caption: str | None) -> None:
    await bot.send_document(
        chat_id=chat_id,
        document=await _read(f),
        filename=f.name,
        caption=caption,
        parse_mode=_parse_mode_for(caption),
    )


async def _send_album(bot: Bot, chat_id: int, chunk: list[Path], caption: str | None) -> None:
    media = []
    for idx, f in enumerate(chunk):
        item_caption = caption if idx == 0 else None
        data = await _read(f)
        item = InputMediaVideo if _category(f) == "video" else InputMediaPhoto
        media.append(item(media=data, filename=f.name, caption=item_caption, parse_mode=_parse_mode_for(item_caption)))
    await bot.send_media_group(chat_id=chat_id, media=media)


async def send_files(bot: Bot, chat_id: int, files: list[Path], caption: str | None) -> None:
    files = sorted(files, key=lambda p: str(p))
    big = [f for f in files if f.stat().st_size > config.MAX_FILE_BYTES]
    small = [f for f in files if f.stat().st_size <= config.MAX_FILE_BYTES]

    if big:
        await bot.send_message(
            chat_id=chat_id,
            text=f"skipped (>50MB): {', '.join(f.name for f in big)}",
        )

    if not small:
        return

    images = [f for f in small if _category(f) == "image"]
    videos = [f for f in small if _category(f) == "video"]
    docs = [f for f in small if _category(f) == "application"]

    first_caption_used = False

    for chunk in _chunks(images, ALBUM_MAX):
        cap = caption if not first_caption_used else None
        if len(chunk) == 1:
            await _send_photo(bot, chat_id, chunk[0], cap)
        else:
            await _send_album(bot, chat_id, chunk, cap)
        first_caption_used = True

    for f in videos:
        cap = caption if not first_caption_used else None
        await _send_video(bot, chat_id, f, cap)
        first_caption_used = True

    for f in docs:
        cap = caption if not first_caption_used else None
        await _send_doc(bot, chat_id, f, cap)
        first_caption_used = True
