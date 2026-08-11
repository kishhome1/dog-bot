# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Barbos — a Telegram Mini App (in Russian) that reminds a *family* (not a group chat) to walk the dog, tracks who walked it and when (with duration/notes), and tracks medical treatments (ticks/deworming/vaccines). All UI (onboarding, logging walks, medicine, stats) lives in a Telegram Mini App backed by a REST API; the bot (`bot.py`) is only the entry point (`/start`) and the push-notification channel.

See `TZ_Barbos_MiniApp.md` (gitignored — private planning doc, not in the repo history) for the full spec this was built against.

## Architecture — two independent processes, one Postgres

```
bot.py            → /start (WebApp button) + reminder scheduling/sending
api/main.py        → FastAPI: REST API + serves miniapp/ as static files
database.py          → shared data-access layer, imported by BOTH bot.py and api/*
```

`bot.py` and `api/main.py` are meant to run as **separate deployments** (two Railway services in production — see README). Neither touches `psycopg2` directly; both go through `database.py`'s functions (`create_family`, `add_walk`, `get_stats`, etc.). This matters because the two processes don't share memory — see "Reminder scheduling" below for why that shapes the design.

- `database.py` — all Postgres access via `psycopg2`, connection string from `DATABASE_URL`, opened/closed per call via `get_connection()` (commit-on-success, no persistent pool). Rows are `RealDictRow`s (dict-like, `row["column"]`). `init_db()` creates the schema (`families`, `family_members`, `reminder_times`, `walks`, `treatments`) and is called by both processes at startup — it's safe to call repeatedly (see the `family_id` column check before dropping the old chat_id-schema `walks` table; **never** make that drop unconditional, it would wipe live walk history on every restart).
- `api/auth.py` — validates Telegram WebApp `initData` (HMAC-SHA256 per Telegram's documented algorithm) from an `Authorization: tma <initData>` header. `get_telegram_user` validates only; `get_current_member` additionally requires existing family membership (`db.get_member_by_tg_user_id`). A Mini App user's `tg_chat_id` is always set equal to their `tg_user_id` at family-creation/join time — Telegram private chat_id == user_id, and initData never exposes a separate chat_id, so there's no other source for it.
- `api/routers/*.py` — one router per resource (`family`, `walks`, `treatments`, `stats`), thin: validate via `Depends(get_current_member)`, call `db.*`, return pydantic models from `api/schemas.py`.
- `api/constants.py` — treatment interval/urgency thresholds (`TREATMENT_INTERVALS`, `compute_status()`) — the single source of truth for status color/days-remaining/progress-bar-percent, computed server-side and sent to the Mini App as data, not recomputed in JS.
- `miniapp/` — vanilla HTML/CSS/JS, **no build step**, loaded as native ES modules (`<script type="module">`). `js/api.js` is the only place that calls `fetch()`; every screen module (`today.js`, `medicine.js`, `stats.js`, `onboarding.js`) imports it rather than calling `fetch` directly. `js/state.js` holds the tiny in-memory session state (`family_id`, member roster for avatar colors/name lookups) populated once from `/api/auth` after login.

## Reminder scheduling model

This is the part that's easy to get wrong, because it spans two processes that don't talk to each other directly:

- The old (pre-Mini-App) bot rescheduled a reminder **synchronously**, in-process, the instant a walk button was pressed. That doesn't work anymore: walks are now written by the **api** process, but `job_queue` jobs live in the **bot** process's memory. There is no IPC between them.
- Instead, `bot.py` runs `reconcile_reminders()` on a `run_repeating` job (every 5 minutes) **and** once at startup via `post_init()`. Each tick fully rebuilds the managed jobs (`reminder_interval_*`, `reminder_fixed_before_*`, `reminder_fixed_at_*`) from the current DB state (`families`, `reminder_times`, last walk) — Postgres is the single source of truth, not the process's memory. This replaces both the old `post_init`-only restart recovery *and* the old instant-reschedule-on-walk.
- `interval` mode: one `run_once` job per family, timed at `last_walk.walked_at + interval_hours` (or `family.created_at` if no walk yet). `send_interval_reminder` re-checks `get_last_walk` before actually sending — if a walk landed after the job was scheduled, it silently skips (the next reconciliation tick will have already computed the correct next time).
- `fixed` mode: `run_daily` jobs per `reminder_times` row, for "1h before" and "at time" (both fire unconditionally — only the "+1h after" follow-up is conditional). The "+1h after" nudge (`send_nudge`, shared with interval mode) is scheduled dynamically via `schedule_once()` (cancel-by-name then `run_once` — the same pattern the old `reschedule_reminder` used) and checks `get_last_walk` before sending, so it silently no-ops if the walk was already logged. This is how "cancel the remaining reminder after a walk is logged" (per the spec) is achieved *without* cross-process job cancellation.
- All reminders go to **every** `family_members.tg_chat_id`, not a single `chat_id` — see `send_to_family()`, which catches `TelegramError` per-recipient so one blocked/broken chat doesn't stop the rest of the family from being notified.
- **Known gap:** `reminder_times.time_of_day` has no per-family timezone — it's interpreted in whatever timezone the JobQueue's scheduler runs in (UTC by default). The schema (per the spec) has no timezone column; this wasn't in scope.

## Onboarding / auth flow

No `ConversationHandler` in the bot anymore — onboarding is entirely in the Mini App (`miniapp/js/onboarding.js`) calling `POST /api/family` (create) or `POST /api/family/join` (second member, via `/start invite_<code>` deep link → bot passes the code through in the WebApp button URL → Mini App auto-joins on load, skipping the onboarding steps). `compute_interval()`/breed/age heuristics from the old bot are gone entirely — `interval_hours` is now a direct user input.

## Language

All user-facing strings, comments, and docstrings in this codebase are in Russian. Match that when adding to `bot.py`/`database.py`/`api/*`/`miniapp/*`/`README.md` unless told otherwise.
