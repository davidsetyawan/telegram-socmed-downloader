# Telegram SocMed Downloader Bot

A small Telegram bot that downloads Instagram and Twitter/X media via `gallery-dl`.
Only whitelisted Telegram users are served. Admin uploads separate
`cookies_instagram.txt` and `cookies_twitter.txt` to unlock private content.

## Requirements

- Python 3.10+
- A Telegram bot token (create one via @BotFather)
- A Telegram user ID for the admin (use @userinfobot)

## Setup

```bash
cd /data/belajar/telegram-socmed-downloader
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
# edit .env and set BOT_TOKEN + ADMIN_ID
```

## Configuration

`.env` is auto-loaded at startup. The same variables can still be exported in
the shell; shell values take precedence over `.env`.

Required keys:

| Variable    | Description |
|-------------|-------------|
| `BOT_TOKEN` | Token from @BotFather |
| `ADMIN_ID`  | Telegram user ID allowed to run admin commands |

Optional keys:

| Variable         | Default   | Description |
|------------------|-----------|-------------|
| `ALBUM_MAX`      | 10        | Max items per Telegram media-group |
| `MAX_FILE_BYTES` | 52428800  | Public Bot API cap (50 MiB) |
| `BASE_URL`       | (empty)   | Local Bot API server URL, if used |

## Run

```bash
.venv/bin/python bot.py
```

`bot.py` reads `BOT_TOKEN` and `ADMIN_ID` from `.env`. To override from the
shell instead:

```bash
BOT_TOKEN=... ADMIN_ID=... .venv/bin/python bot.py
```

## Admin commands

- `/whitelist_add <user_id>` — add a Telegram user ID to the whitelist
- `/whitelist_remove <user_id>` — remove a Telegram user ID
- `/whitelist_list` — show all whitelisted IDs
- `/uploadcookies` — then send a Netscape-format cookies file; the filename must contain `instagram`, `twitter`, or `x.com` so the bot knows which bucket to store it in

## Cookies

Cookies are stored as **two separate files** — one per host:

- `storage/cookies_instagram.txt` for Instagram
- `storage/cookies_twitter.txt` for Twitter / X

The bot picks the right file automatically based on the URL the user sends.
If the matching file is missing, the request is blocked with a message
to the user and a hint for the admin.

To upload cookies, the admin runs `/uploadcookies` and then sends a
Netscape-format cookies file. **The filename must contain `instagram`,
`twitter`, or `x.com`** (case-insensitive substring match). Examples that work:

- `www.instagram.com_cookies.txt` → stored as Instagram cookies
- `twitter.com_cookies.txt` → stored as Twitter cookies
- `x.com_cookies.txt` → stored as Twitter cookies
- `InstagramExport.txt` → Instagram

Examples that are rejected:

- `cookies.txt` (no host marker)
- `instagram_and_twitter.txt` (ambiguous — contains both)

Export cookies in **Netscape** format using the browser extension
**"Get cookies.txt LOCALLY"** while logged in to the relevant site.
Re-upload whenever cookies expire; the upload atomically replaces the
existing file.

## User flow

Whitelisted user sends any Instagram or Twitter/X URL → bot replies
`starting download...`, downloads via gallery-dl, sends media as
Telegram albums (max 10 each). Files larger than 50 MB are skipped
with a notification. Non-whitelisted users get no reply.
