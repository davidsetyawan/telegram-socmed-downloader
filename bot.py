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
                bucket = cookies_store.bucket_for_host(url) or "this host"
                await update.message.reply_text(
                    f"no {bucket} cookies uploaded yet; admin must place "
                    f"cookies_{bucket}.txt in storage/"
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
