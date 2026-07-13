# CLAUDE.md

Rules and context for Claude (or any AI assistant) working in this repository. Follow strictly.

> Owner note: parts marked [FILL IN] are placeholders. First task for Claude in a new project: inspect the real repository files, fill these sections in accurately, and give me the updated file to commit. Do not invent anything — only write what the actual code shows.

## 1. Project overview
A Telegram bot (Arabic/English) that downloads videos and images from multiple platforms — YouTube, Facebook, Instagram, TikTok, Twitter/X, Threads, Reddit, Pinterest, Snapchat and others — and re-uploads them to Telegram (files up to 2GB). It is aimed at Telegram users/communities, operated by an admin, and includes member management, a mandatory survey, subscriptions, referrals, daily download limits, content filtering, a smart `file_id` cache, and automatic PostgreSQL backups. It is a backend-only bot (no web frontend). Stage: working, actively maintained (recent commits fix platform-specific download issues).

## 2. Tech stack
- Frontend: None (no web/mobile UI). The user interface is entirely inside Telegram — messages, inline keyboards, and callback buttons rendered by the bot via Pyrogram.
- Backend: Python 3.8+. Telegram client via **Pyrogram 2.0.106** (+ `tgcrypto`). Downloading via **yt-dlp**, **gallery-dl** (image albums/carousels), and **curl_cffi** (HTTP with browser TLS fingerprint). Media processing via **ffmpeg/ffprobe** (external binaries). Config via `python-dotenv`.
- Database: **PostgreSQL** accessed with `psycopg2-binary`, using a threaded connection pool (`subscription_db.py`). Tables in the real code: `users`, `settings`, `forced_channels`, `fsub_user_passed`, `media_cache`, `download_history`, `referrals`, `moderation`, `member_survey`, `admin_questions`, `member_answers`.
- Auth: Telegram-native. The bot authenticates to Telegram with `PYROGRAM_API_ID` / `PYROGRAM_API_HASH` / `BOT_TOKEN`. Privileged/admin commands are gated by matching the sender's Telegram user id against `ADMIN_ID`. There is no separate user password/login system.
- Infrastructure / other: Runs as a long-lived Python process (`run.sh` → `python3 bot.py`). No Docker. CI via GitHub Actions (`.github/workflows/tests.yml`) runs a `py_compile` syntax gate + the pytest suite on every push and pull request. Helper scripts: `setup_postgres.py` (create tables), `update_ytdlp.sh` (update yt-dlp/gallery-dl/curl_cffi), automatic backups to a Telegram channel (`pg_backup.py`). Optional cookie files live under `cookies/` (gitignored). Logs to `bot_standalone.log`.

## 3. Project structure
- `bot.py` — main application and entry point (~6,575 lines): Pyrogram handlers, commands (e.g. `/start`, `/cookies`, `/backup`, `/update`, `/uncache`, `/history`, `/dlstats`, `/blockacc`, `/ban`/`/unban`), download orchestration, upload, caching, member/admin flows.
- `subscription_db.py` — PostgreSQL data layer: connection pool, table creation, and all read/write logic for members, subscriptions, settings, cache, history, referrals, moderation, and survey data.
- `queue_manager.py` — per-user download queue with a cooldown/rate limit and concurrent processing (`DownloadQueueManager`, `DownloadTask`).
- `url_utils.py` — pure URL helpers: platform detection, SSRF/private-host safety (`is_safe_url`), cache keys, URL extraction from text.
- `cookies_manager.py` — selects the per-platform cookie file for a URL, reads Netscape cookie files, and validates cookie freshness.
- `link_resolvers.py` — special resolvers: Snapchat Spotlight raw-video extraction and music-link handling (Shazam/Apple Music/Spotify → search & download from YouTube).
- `content_filter.py` — pre-download filtering: adult/blocked domains + keyword lists, blocked source accounts, and enable/disable toggles.
- `video_processing.py` — ffmpeg/ffprobe: thumbnail generation and finalizing video to H.264/AAC + faststart for Telegram.
- `download_errors.py` — classifies yt-dlp error text (DRM, geo-restriction, cookie issues, age/sensitive-restricted) so the bot reacts correctly.
- `translations.py` — Arabic/English UI strings (`t()`).
- `pg_backup.py` — export/restore the database as SQL/JSON and send backups to a Telegram channel.
- `setup_postgres.py` — creates the `users` and `settings` tables (initial DB setup helper).
- `tests/` — pytest suite for the pure/logic modules: `test_url_utils.py`, `test_content_filter.py`, `test_cookies_manager.py`, `test_download_errors.py`, `test_link_resolvers.py`, `test_queue_manager.py`, plus `conftest.py`.
- Config/docs: `requirements.txt`, `requirements-dev.txt`, `env.example`, `run.sh`, `update_ytdlp.sh`, `.gitignore`, `README.md`, `INSTALLATION_GUIDE.md`, `QUICK_START.md`.

## 4. Commands
- Install dependencies: `pip install -r requirements.txt` (runtime). For tests/dev tools also `pip install -r requirements-dev.txt`. External binary required: `ffmpeg` (with `ffprobe`). First-time DB setup: `python3 setup_postgres.py`.
- Run in development: create `.env` from `env.example`, then `python3 bot.py` (or `bash run.sh`). Requires a reachable PostgreSQL and valid Telegram credentials in `.env`.
- Run tests: `python3 -m pytest -q` (from the repo root).
- Build for production: No build/compile step (pure Python). "Production" = run the same `python3 bot.py` as a long-lived process (e.g. under systemd/screen) with `.env` configured and PostgreSQL available. Keep downloaders current with `bash update_ytdlp.sh`.

## 5. Non-negotiable rules
1. Real functionality only. No placeholder buttons, no fake or mock data presented as real, no fake API calls, no TODO-stub "features." If something cannot be real yet (missing keys or services), state exactly what is missing, build the real code path anyway, and add a clearly labeled safe fallback.
2. Inspect before editing. Read the actual files first. Never assume a file, route, endpoint, table, column, package, or environment variable exists — verify it or ask the owner.
3. Never restart from scratch or rewrite the architecture without the owner's explicit approval.
4. Small incremental changes. One feature or fix at a time. Everything that already works must keep working. Never delete previous work without asking.
5. Honest verification. Never claim tests passed or a build succeeded without actually running it. If not run, say "Not run" and provide the exact commands.
6. Security. No secrets in code — use environment variables, keep .env in .gitignore, keep .env.example updated with placeholder values. Validate all input server-side, use parameterized queries, hash passwords properly.
7. Complete features only. Every feature includes the full real data flow (UI → API → database → UI), client and server validation, loading/empty/error/success states, and server-side permission checks where relevant.
8. Premium UI. Modern, clean, consistent spacing and typography, proper icon sets, subtle animations. Full RTL support and modern Arabic fonts on Arabic screens. No default or amateur-looking UI, no emoji-heavy design.

## 6. Definition of done
A task is done only when: the code path is fully real end to end, errors and edge cases are handled, nothing that previously worked is broken, no secrets were exposed, and the final report honestly states what was and was not verified.

## 7. End-of-task report format
Every task ends with: Implemented / Files changed / Tests-build result / How to run / Limitations.

## 8. Current status
- Working now: Multi-platform downloading (video/image) via yt-dlp/gallery-dl with per-platform cookie support; Pinterest multi-media support (video pins + multi-image carousels/Idea Pins sent as Telegram albums) with a cookie-less fallback through Pinterest's public PinResource/pidgets endpoints (`PINTEREST_PROXY_HOSTS`), same mirror pattern as Instagram/TikTok/Twitter; Substack Notes video (`substack.com/@user/note/c-…`) via Substack's public reader-comment + video/src endpoints (cookie-less, signed Mux playback resolved automatically); quality/audio-only options; smart `file_id` cache to re-send previously downloaded media without re-downloading; ffmpeg finalize + thumbnails; per-user queue with rate limiting; content filtering (adult/blocked domains, blocked source accounts) before download; download-error classification with cookie-less retry; PostgreSQL storage with connection pooling; member management (mandatory survey, tiered ban/warn, daily limits, referrals, download history); admin-managed exemption list (`exempt_user_ids` setting: excluded from broadcasts and reminders, exempt from forced subscription; managed via `/exempt`, `/unexempt`, `/exemptlist` or the ⭐ panel inside the broadcast/reminder/forced-sub screens, incl. exempt-only broadcast); Arabic/English translations; automatic + manual backups to a Telegram channel. Pinned dependency versions in `requirements.txt`. A pytest suite covers the pure-logic modules.
- In progress: No explicitly tracked in-progress work in the repo. Recent git history shows ongoing fixes to platform-specific download paths (Instagram Reels via public mirror without cookies, Facebook ad-injection avoidance, yt-dlp/gallery-dl/curl_cffi updater).
- Next planned: None recorded in the repo. Practical follow-ups: keep yt-dlp/gallery-dl updated (`update_ytdlp.sh`), and optionally add smart mirror failover (remember the last working host per platform). Earlier housekeeping items are now done: `LICENSE` added (MIT), README GitHub badge points to the real repo, and the mojibake emoji in `cookies_manager.py` are fixed.

Keep sections 1–4 and 8 updated as the project evolves.
