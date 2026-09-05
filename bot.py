import asyncio
import contextlib
import logging
import os
import re
import shutil
import time
from telegram import Update
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
    r"https?://(?:www\.)?"
    r"(?:instagram\.com/(?:p|reel)/[\w-]+(?:/\?.*)?/?"
    r"|instagram\.com/[\w.\-]+/?"
    r"|(?:twitter|x)\.com/[^/]+(?:/status/\d+)?/?"
    r")",
    re.IGNORECASE,
)

chat_locks: dict[int, asyncio.Lock] = {}


@contextlib.contextmanager
def _tmpdir():
    """Yield a fresh tmp/<ts>_<rand> directory and rmtree it on exit."""
    parent = paths.TMP_DIR
    parent.mkdir(parents=True, exist_ok=True)
    d = parent / f"{int(time.time() * 1000)}_{os.urandom(3).hex()}"
    d.mkdir(parents=True, exist_ok=True)
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not whitelist.is_allowed(update.effective_user.id):
        return
    await update.message.reply_text("welcome")


def _is_admin(user_id: int) -> bool:
    return user_id == config.ADMIN_ID


async def cmd_uploadcookies(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id if update.effective_user else None
    if not _is_admin(uid):
        _log.info("cmd_uploadcookies ignored: uid=%s is not admin", uid)
        return
    _log.info("cmd_uploadcookies: uid=%s (now arm-less)", uid)
    await update.message.reply_text(
        "send the cookies file (any document from admin is accepted); "
        "filename must contain 'instagram' or 'twitter' "
        "(e.g. www.instagram.com_cookies.txt)"
    )


async def handle_cookie_upload(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    uid = update.effective_user.id if update.effective_user else None
    if not _is_admin(uid):
        _log.info("cookie upload ignored: uid=%s is not admin", uid)
        return
    doc = update.message.document
    if doc is None:
        _log.info("cookie upload ignored: message had no document")
        return
    _log.info("cookie upload starting: filename=%s uid=%s", doc.file_name, uid)
    try:
        bucket = cookies_store.bucket_name_for_filename(doc.file_name or "")
        file = await doc.get_file()
        buf = await file.download_to_memory()
        target = cookies_store.save_for_bucket(bytes(buf), bucket)
    except cookies_store.CookieError as e:
        await update.message.reply_text(str(e))
        return
    except Exception:
        _log.exception("cookie upload failed")
        await update.message.reply_text("cookie upload failed")
        return
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
    lock = chat_locks.setdefault(chat_id, asyncio.Lock())
    async with lock:
        with _tmpdir() as out_dir:
            cookies = cookies_store.get_path_for_host(url)
            if cookies is None:
                bucket = cookies_store.bucket_for_host(url) or "this"
                await update.message.reply_text(
                    f"no {bucket} cookies uploaded yet; admin must "
                    f"/uploadcookies first (filename must contain '{bucket}')"
                )
                return
            try:
                files, kwdicts = await asyncio.to_thread(
                    downloader.run, url, out_dir, cookies
                )
            except downloader.DownloadError as e:
                await update.message.reply_text(str(e))
                return
            if not files:
                bucket = cookies_store.bucket_for_host(url)
                if bucket == "instagram":
                    hint = (
                        "no media found. if this is a profile, your "
                        "instagram cookies may be stale or your account "
                        "may not have access to it."
                    )
                else:
                    hint = "no media found"
                await update.message.reply_text(hint)
                return
            caption = sender.build_caption(url, kwdicts, files)
            await sender.send_files(context.bot, chat_id, files, caption)


def build_app() -> Application:
    builder = ApplicationBuilder().token(config.BOT_TOKEN)
    if config.BASE_URL:
        builder = builder.base_url(config.BASE_URL)
    app = builder.build()

    app.add_handler(CommandHandler("start", cmd_start))
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
    paths.ensure()
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
