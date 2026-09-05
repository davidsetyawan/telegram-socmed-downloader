import asyncio
import logging
import re
import shutil
import time

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
import cookies_store
import downloader
import paths
import sender
import whitelist

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
_log = logging.getLogger("bot")

URL_RE = re.compile(
    r"https?://(www\.)?(instagram\.com|twitter\.com|x\.com)/\S+",
    re.IGNORECASE,
)

HELP_TEXT = (
    "send an instagram or twitter/x URL to download.\n"
    "supported: single post, full profile.\n"
    "files larger than 50MB are skipped."
)

chat_locks: dict[int, asyncio.Lock] = {}


def _is_admin(user_id: int) -> bool:
    return user_id == config.ADMIN_ID


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not whitelist.is_allowed(update.effective_user.id):
        return
    await update.message.reply_text("welcome")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not whitelist.is_allowed(update.effective_user.id):
        return
    await update.message.reply_text(HELP_TEXT)


async def cmd_uploadcookies(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        return
    context.user_data["awaiting_cookies"] = True
    await update.message.reply_text(
        "send the cookies file; filename must contain 'instagram' or 'twitter' "
        "(e.g. www.instagram.com_cookies.txt)"
    )


async def handle_cookie_upload(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not _is_admin(update.effective_user.id):
        return
    if not context.user_data.get("awaiting_cookies"):
        return
    doc = update.message.document
    if doc is None:
        return
    try:
        try:
            bucket = cookies_store.bucket_name_for_filename(doc.file_name or "")
        except cookies_store.CookieError as e:
            await update.message.reply_text(str(e))
            return
        file = await doc.get_file()
        buf = bytearray()
        async for chunk in file.download_chunked():
            buf.extend(chunk)
        target = cookies_store.save_for_bucket(bytes(buf), bucket)
    except cookies_store.CookieError as e:
        await update.message.reply_text(str(e))
        return
    except Exception:
        _log.exception("cookie upload failed")
        await update.message.reply_text("cookie upload failed")
        return
    context.user_data["awaiting_cookies"] = False
    await update.message.reply_text(f"cookies updated: {target.name}")


async def cmd_wl_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("usage: /whitelist_add <user_id>")
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("user_id must be an integer")
        return
    whitelist.add(uid)
    await update.message.reply_text(f"whitelist size: {len(whitelist.load())}")


async def cmd_wl_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("usage: /whitelist_remove <user_id>")
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("user_id must be an integer")
        return
    whitelist.remove(uid)
    await update.message.reply_text(f"whitelist size: {len(whitelist.load())}")


async def cmd_wl_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        return
    ids = sorted(whitelist.load())
    await update.message.reply_text(", ".join(str(i) for i in ids) or "(empty)")


def _host_bucket(url: str) -> str:
    lower = url.lower()
    if "instagram.com" in lower:
        return "instagram"
    return "twitter"


async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not whitelist.is_allowed(update.effective_user.id):
        return
    if update.message.text is None:
        return
    m = URL_RE.search(update.message.text)
    if m is None:
        return
    url = m.group(0)
    chat_id = update.effective_chat.id

    # Outer try: catch Telegram API errors (network blips, TimedOut).
    # Without this, a single failed edit_text can kill the bot.
    try:
        lock = chat_locks.setdefault(chat_id, asyncio.Lock())
        async with lock:
            status = await update.message.reply_text("starting download...")
            out_dir = paths.TMP_DIR / f"{chat_id}_{int(time.time())}"
            out_dir.mkdir(parents=True, exist_ok=True)
            try:
                cookies = cookies_store.get_path_for_host(url)
                if cookies is None:
                    bucket = _host_bucket(url)
                    await status.edit_text(
                        f"no {bucket} cookies uploaded yet; admin must "
                        f"/uploadcookies first (filename must contain '{bucket}')"
                    )
                    return
                try:
                    files = await asyncio.to_thread(
                        downloader.run, url, out_dir, cookies
                    )
                except downloader.DownloadError as e:
                    await status.edit_text(str(e))
                    return
                if not files:
                    bucket = _host_bucket(url)
                    if bucket == "instagram":
                        hint = (
                            "no media found. if this is a profile, your "
                            "instagram cookies may be stale or your account "
                            "may not have access to it. admin can re-upload "
                            "with /uploadcookies."
                        )
                    else:
                        hint = "no media found"
                    await status.edit_text(hint)
                    return
                await sender.send_files(context.bot, chat_id, files)
                await status.edit_text(f"done: {len(files)} file(s)")
            finally:
                shutil.rmtree(out_dir, ignore_errors=True)
    except TelegramError as e:
        _log.warning(
            "telegram api error during handle_url for url=%s chat=%s: %s",
            url, chat_id, e,
        )


def build_app() -> Application:
    builder = ApplicationBuilder().token(config.BOT_TOKEN)
    if config.BASE_URL:
        builder = builder.base_url(config.BASE_URL)
    app = builder.build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("uploadcookies", cmd_uploadcookies))
    app.add_handler(
        MessageHandler(
            filters.Document.ALL & filters.User(config.ADMIN_ID),
            handle_cookie_upload,
        )
    )
    app.add_handler(CommandHandler("whitelist_add", cmd_wl_add))
    app.add_handler(CommandHandler("whitelist_remove", cmd_wl_remove))
    app.add_handler(CommandHandler("whitelist_list", cmd_wl_list))
    app.add_handler(
        MessageHandler(filters.Regex(URL_RE) & ~filters.COMMAND, handle_url)
    )
    return app


async def main() -> None:
    _log.info("Application starting; admin=%d", config.ADMIN_ID)
    app = build_app()
    async with app:
        await app.start()
        await app.updater.start_polling()
        try:
            await asyncio.Event().wait()
        finally:
            await app.updater.stop()


if __name__ == "__main__":
    asyncio.run(main())
