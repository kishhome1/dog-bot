# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Telegram bot (in Russian) that reminds a household to walk the dog, tracks who walked it and when, and stores per-walk notes. Two-file Python project built on `python-telegram-bot`.

## Commands

```bash
# install deps (Python 3.10+)
pip install -r requirements.txt

# configure token: copy .env.example to .env and put the BotFather token in BOT_TOKEN
cp .env.example .env

# run
python bot.py
```

There is no test suite, linter, or build step in this repo.

## Architecture

- `bot.py` — all Telegram handlers, scheduling logic, and the `main()` entry point.
- `database.py` — all SQLite access, wrapped behind plain functions (`add_walk`, `get_stats`, `set_interval`, etc.). `bot.py` never touches `sqlite3` directly; it always goes through `db.*`. Uses a single `dog_walks.db` file (path hardcoded as `DB_PATH`), opened/closed per call via the `get_connection()` context manager (commit-on-success, no persistent connection).

### Reminder scheduling model

This is the part that spans both files and is easy to get wrong:

- Reminders are **not** cron-like fixed times. Each reminder is scheduled `interval_hours` after the *last recorded walk*, via `python-telegram-bot`'s `job_queue` (`run_once`, not `run_repeating`).
- Jobs are named `reminder_{chat_id}` and `nudge_{chat_id}`. `reschedule_reminder()` always cancels existing jobs with those names before scheduling new ones — this is the mechanism that keeps only one reminder per chat live at a time.
- Marking a walk (button press) calls `schedule_next_reminder()`, which reads `interval_hours` from `chat_settings` and reschedules from *now*.
- If nobody acknowledges a reminder within an hour, `send_nudge` fires once as a soft follow-up (it checks `get_last_walk` again in case a walk was logged in the meantime).
- On process restart, `post_init()` reconstructs every chat's pending reminder from `chat_settings` + the last walk timestamp in the DB — this is how the bot survives restarts without a persistent job store. Any change to how reminders are scheduled elsewhere should be mirrored here or restored state will drift from live state.

### Conversation flow (`/start`)

A `ConversationHandler` (states `ASK_NAME` → `ASK_BREED` → `ASK_AGE` → `ASK_NEXT_WALK`) walks the user through setting up a pet profile. `compute_interval()` derives a starting `interval_hours` from age + breed keywords (see `SMALL_BREED_KEYWORDS`) — this is a heuristic default, not a vet recommendation, and is always overridable via `/setinterval`. Setup state lives transiently in `context.chat_data["setup"]` until `set_pet_profile()` persists it.

### Note-taking flow

Notes are attached to a walk via Telegram's reply mechanism rather than a stateful conversation: `note_button_callback` sends a prompt message and records `(prompt_message_id, walk_id)` in the in-memory `pending_note_prompts` dict; `handle_text` only accepts a note if the incoming message is a reply to that exact prompt message. This reply-based design is deliberate — it lets the bot work in groups without disabling Telegram's bot privacy mode (see README's "Заметки к прогулке работают через reply" note). `pending_note_prompts` is in-memory only and does not survive a restart.

### Database migrations

`init_db()` creates tables if missing, then adds new columns to `chat_settings` (e.g. `breed`, `age_years`) via `ALTER TABLE`, swallowing `OperationalError` if the column already exists. There's no migration framework — new columns follow this same try/except-add pattern directly in `init_db()`.

## Language

All user-facing strings, comments, and docstrings in this codebase are in Russian. Match that when adding to `bot.py`/`database.py`/`README.md` unless told otherwise.
