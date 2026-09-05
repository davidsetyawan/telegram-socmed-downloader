import mimetypes
from pathlib import Path

from telegram import Bot, InputMediaPhoto

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
    """Send a multi-image album via send_media_group.

    Telegram requires all items in a media group to be the same type; only
    photos are reliable here. Videos and mixed types go through their
    dedicated per-file send_* methods.
    """
    media = []
    for idx, f in enumerate(chunk):
        with open(f, "rb") as fh:
            data = fh.read()
        item_caption = caption if idx == 0 else None
        media.append(InputMediaPhoto(media=data, filename=f.name, caption=item_caption))
    await bot.send_media_group(chat_id=chat_id, media=media)


async def send_files(bot: Bot, chat_id: int, files: list[Path]) -> None:
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

    caption = f"{len(files)} file(s) downloaded"
    first_caption_used = False

    # Multi-image albums via send_media_group (only when 2+ images).
    for chunk in _chunks(images, config.ALBUM_MAX):
        if len(chunk) == 1:
            await _send_image(bot, chat_id, chunk[0], caption if not first_caption_used else None)
        else:
            await _send_image_album(bot, chat_id, chunk, caption if not first_caption_used else None)
        first_caption_used = True

    # Each video is sent individually with send_video (reliable + supports_streaming).
    for f in videos:
        await _send_video(bot, chat_id, f, caption if not first_caption_used else None)
        first_caption_used = True

    # Documents (text sidecars, unknown types).
    for f in docs:
        await _send_doc(bot, chat_id, f, caption if not first_caption_used else None)
        first_caption_used = True
