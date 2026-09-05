# Repository Guidelines

## Project Overview

A Telegram bot (`@anotherFeelingBot`) that downloads Instagram and Twitter/X media
via `gallery-dl`. Whitelist-gated — only whitelisted Telegram user IDs are served.
Admin uploads per-host `cookies.txt` files to unlock private/age-gated content.
Built on `python-telegram-bot` v21 (async) + `gallery-dl` Python API.
Single Python 3.10+ codebase, ~630 LOC, no tests yet (TODO).

## Architecture & Data Flow

**Single-process, async event loop.** All long-running work (gallery-dl downloads)
runs in a worker thread via `asyncio.to_thread` so the bot stays responsive.

```
Telegram update
    │
    ▼
bot.py:handle_url  (asyncio.Lock per chat, sequential within a chat)
    │
    ├─► cookies_store.get_path_for_host(url)  ──► storage/cookies_{instagram,twitter}.txt
    │      (host → bucket mapping: instagram.com → ig, twitter.com / x.com → tw)
    │
    ├─► downloader.run(url, out_dir, cookies)  ──► gallery-dl API
    │      (blocking; wrapped in asyncio.to_thread)
    │      (raises DownloadError on auth/no-extractor/generic)
    │
    ├─► sender.send_files(bot, chat_id, files)
    │      • images (1)   → send_photo
    │      • images (2+)  → send_media_group (album)
    │      • videos       → send_video (per file, supports_streaming=True)
    │      • other        → send_document
    │      • >50 MB       → skipped with a message
    │
    └─► shutil.rmtree(out_dir)  in finally
```

`chat_locks: dict[int, asyncio.Lock]` (module-level in `bot.py`) serializes
downloads per chat; concurrent users run in parallel.

## Key Directories

| Path | Purpose |
|------|---------|
| `bot.py` | Entry point, handler wiring, regex, per-chat lock map |
| `config.py` | Env loading (`.env` via `python-dotenv`), required BOT_TOKEN/ADMIN_ID |
| `paths.py` | `DATA_DIR = ./storage`, `TMP_DIR = ./tmp` (auto-created) |
| `whitelist.py` | JSON file `storage/whitelist.json` — `{"user_ids": [int, ...]}` |
| `cookies_store.py` | Two cookie files; filename → bucket routing; atomic write |
| `downloader.py` | gallery-dl wrapper + `DownloadError` mapping |
| `sender.py` | Per-type Telegram sends (photo/video/document/media_group) |
| `storage/whitelist.json` | Persisted whitelist |
| `storage/cookies_instagram.txt` | Per-host cookies (Netscape format) |
| `storage/cookies_twitter.txt` | Per-host cookies (Netscape format) |
| `tmp/<chat_id>_<ts>/` | Per-download scratch dir; auto-cleaned after send |
| `.env` | Real secrets (gitignored) |
| `.env.example` | Template (committed) |

## Development Commands

```bash
# Setup
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env  # then fill in BOT_TOKEN + ADMIN_ID

# Run
.venv/bin/python bot.py

# Run with overrides
BOT_TOKEN=... ADMIN_ID=... .venv/bin/python bot.py

# Quick sanity check (no Telegram needed)
.venv/bin/python -c "import bot; app = bot.build_app(); print('OK')"

# Module unit checks (no Telegram)
.venv/bin/python -c "
import os; os.environ.setdefault('BOT_TOKEN','x'); os.environ.setdefault('ADMIN_ID','1')
import config, cookies_store, sender
print(config.BOT_TOKEN, config.ADMIN_ID, config.ALBUM_MAX)
print(cookies_store.bucket_name_for_filename('x.com_cookies.txt'))
"

# Lint / format
.venv/bin/python -m py_compile *.py        # syntax check
.venv/bin/pip install ruff && .venv/bin/ruff check .
```

`requirements.txt` is pinned:
- `python-telegram-bot[ext]==21.6`
- `gallery-dl==1.30.1`
- `python-dotenv==1.0.1`

## Code Conventions & Common Patterns

- **Async-first.** `python-telegram-bot` v21 is async; never use blocking
  calls in handlers. Wrap blocking work in `asyncio.to_thread`.
- **Module-level `chat_locks`** dict for per-resource serialization. Use
  `chat_locks.setdefault(chat_id, asyncio.Lock())` to lazy-init.
- **Atomic file writes.** Always write `*.tmp`, `fsync`, then `os.replace`.
  See `cookies_store.save_for_bucket` and `whitelist.save`.
- **Custom `DownloadError`** in `downloader.py` carries user-facing strings.
  Handler in `bot.py` does `await status.edit_text(str(e))` on it.
- **Silent on non-whitelisted.** Every public handler starts with
  `if not whitelist.is_allowed(...): return` — no reply, no error.
- **Admin gate** is `update.effective_user.id == config.ADMIN_ID`. Whitelist
  commands and `/uploadcookies` use this; no shared decorator.
- **Gallery-dl config injection.** `downloader.run` mutates the global
  `gallery_dl.config` via `set((), "base-directory", ...)` and
  `set(("extractor",), "cookies", ...)` — `config.load(("--",))` is called
  first to ensure defaults are loaded. There is no per-call `ConfigDict`.
- **File reads in sender.** Files are read fully into `bytes` before
  passing to `send_photo` / `send_video` / `send_document` /
  `InputMediaPhoto(media=bytes, filename=...)`. Do NOT pass `Path` or
  `InputFile(Path)` — `InputFile.__init__` calls `.read()` on the input
  and `Path` has no `.read()`, leaving the raw `PosixPath` in the request.
- **Cookie filename routing.** `bucket_name_for_filename(fn)` is
  case-insensitive substring match on `instagram`, `twitter`, or `x.com`.
  Ambiguous names (contain both ig + tw markers) are rejected.
- **Per-chat lock** scope is `async with chat_locks.setdefault(chat_id, asyncio.Lock())`
  around the whole download→send→cleanup block, including the `status` reply
  edits.

## Important Files

- `bot.py:212-225` — `async def main()` + `asyncio.run(main())` entry point.
  Required because PTB 21.6's `run_polling` uses `asyncio.get_event_loop()`
  which raises on Python 3.14 with no current loop in the main thread.
- `bot.py:155-184` — `handle_url`: whitelist → URL match → cookies present →
  `asyncio.to_thread(downloader.run)` → `sender.send_files` → edit status
  → `shutil.rmtree` in `finally`.
- `bot.py:67-96` — `handle_cookie_upload`: filename classification, atomic save,
  flags `context.user_data["awaiting_cookies"]`.
- `downloader.py:16-32` — `run()` signature: `(url, out_dir, cookies_path) -> list[Path]`.
  Error mapping for `NoExtractorError`, `AuthenticationError`,
  `AuthorizationError`, generic.
- `sender.py` — per-type send paths. Image albums via `send_media_group`,
  single images via `send_photo`, videos via `send_video` (per file).
- `cookies_store.py:46-66` — `bucket_name_for_filename` is the single source
  of truth for filename→bucket routing.
- `config.py:23-27` — required env vars; missing → `RuntimeError`.

## Runtime/Tooling Preferences

- **Python 3.10+** (tested on 3.14). venv at `.venv/` (gitignored).
- **Bot API**: public `api.telegram.org`. Local Bot API server support via
  `BASE_URL` env (already wired in `bot.build_app`).
- **No git repo** in this project currently. Initialize one if needed; the
  `.gitignore` is already in place.
- **No CI, no test suite, no linter config** yet — single-file conventions
  apply. Add `ruff` + `pytest` when scope grows.
- **No Node, no Docker, no systemd unit** in scope. Run via `.venv/bin/python bot.py`
  under `hub` supervision or `nohup` for long-running.

## Testing & QA

There is no test suite yet. The project is verified by:

- **Module unit checks** (see Development Commands): imports, filename
  routing, sender chunking, whitelist round-trip, cookies atomic write,
  downloader error mapping.
- **Live smoke** via Telegram:
  1. `/start` from admin → "welcome"
  2. `/start` from non-whitelisted → no reply
  3. Send a public IG post URL → "starting download..." → media → "done: N file(s)"
  4. Send a public Twitter profile URL → multiple media groups
  5. `/uploadcookies` then send `www.instagram.com_cookies.txt` → "cookies updated: cookies_instagram.txt"
  6. Reject test: send `cookies.txt` (no host marker) → friendly error
  7. Reject test: send `instagram_and_twitter.txt` → "ambiguous" error
  8. `ls tmp/` after success → empty
- **Known live behavior**:
  - Instagram often returns `429 Too Many Requests` after several requests
    in a short window; gallery-dl logs `Waiting until HH:MM:SS` and blocks
    until reset. This is normal — `starting download...` will stay for up
    to a few minutes with no progress to show.
  - Twitter/X requires auth for almost all content; the bot will block
    the request with "no twitter cookies uploaded yet" unless the admin
    has uploaded `cookies_twitter.txt`.

## Operational Notes

- **Bot process management**: long-running services should use `hub` with
  `name=bot`, `application=.venv/bin/python`, `args=[bot.py]`. Restart
  policy: `on-failure`. Do NOT use plain `bash &` for long runs — PTB
  needs the supervising shell to handle signals.
- **Logs**: PTB logs at INFO by default (`logging.basicConfig` in `bot.py:24-28`).
  Set `LOG_LEVEL=DEBUG` env var if you need verbose httpx/telegram output.
- **Adding new handlers**: register in `bot.build_app()` after the existing
  entries; first match wins. Add admin gate at the top of the callback
  for admin-only commands.
- **Adding new cookie hosts**: extend `_bucket_for_host` and
  `bucket_name_for_filename` patterns in `cookies_store.py` together, then
  add the file path constant `_XXX_PATH`.
