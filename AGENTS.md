# Apple Calendar Skill

Read-only query CLI for the macOS Apple Calendar store (EventKit SQLite).

## Repository Layout

```
apple-calendar-skill/
├── AGENTS.md
├── .env.example          # documents APPLE_CALENDAR_STORE_DIR (test override)
├── .github/workflows/ci.yml   # ubuntu + uv + pytest (Python 3.12)
├── .gitignore            # also blocks *.sqlitedb / *.sqlitedb-wal / -shm
├── LICENSE               # MIT
├── README.md
├── docs/                 # working.md exists; prd.md, rfc.md, test.md
├── scripts/apple-calendar     # thin launcher, runs from a checkout, exec bit on
├── skills/apple_calendar.md   # canonical skill doc (YAML frontmatter)
├── src/apple_calendar/   # __init__.py, __main__.py, timeutil.py, store.py, cli.py
└── tests/                # conftest.py, fixtures.py, test_apple_calendar.py; 31 tests
```

## How to Run

- Directly from a repository checkout without installation: `python3 scripts/apple-calendar <subcommand>`
- After editable package installation: `apple-calendar <subcommand>`
- Set up the development environment: `uv venv && uv pip install -e '.[dev]'` (requires Python 3.9+).

## Read-Only Boundary

The tool is **read-only by construction**. The live database (`~/Library/Group Containers/group.com.apple.calendar/Calendar.sqlitedb`) is never opened directly. Instead, a momentary file snapshot (`Calendar.sqlitedb` plus `-wal` and `-shm` sidecars) is copied into a temporary directory and opened with `sqlite3` in read-only mode (`mode=ro`). The tool has no AppleScript, no EventKit API calls, no SQL mutation statements, and no write path of any kind.

## Time Semantics

Event timestamps in `start_date` and `end_date` store absolute seconds since `2001-01-01 00:00:00 UTC` (Cocoa's `NSDate` reference epoch), while `start_tz` is display-only. All-day events store UTC midnight with timezone `_float`. Treating stored instants as local wall-clock values caused a 7-hour discrepancy on 2026-10-13 (a 12:00 UTC event misread as 12:00 local rather than 05:00 local). To make the right interpretation the only interpretation, the CLI suppresses the raw epoch column and outputs dual fields: `start_utc` (authoritative source of truth) and `start_local` (display).

## Testing and Invariants

- **Offline tests**: `pytest tests/` runs 31 tests fully offline against synthetic SQLite fixture stores configured via the `APPLE_CALENDAR_STORE_DIR` environment override. Tests never touch the live calendar store.
- **On-machine selftest**: `python3 scripts/apple-calendar selftest` checks seven invariants (`store_is_group_container`, `store_not_decoy`, `end_not_before_start`, `allday_tz_not_timezone`, `allday_stored_at_utc_midnight`, `local_zone_is_iana`, `display_roundtrip_sample`) against the active store. Run it on a real Mac.
- **Continuous integration**: GitHub Actions runs `pytest` on Ubuntu (Python 3.12, `uv`). Runners have no Apple store, so only store-independent offline tests execute.

## Maintenance and Version Control

- **Working notes contract**: Maintain `docs/working.md` as the project memory. Every substantive change must append dated bullets under `Changelog` (one change each) and record any new pitfalls under `Lessons Learned`.
- **Version control boundary**: Only commit, push, or open pull requests when explicitly instructed by the user. Keep commits small, focused, and reversible. Never commit personal calendar data or `*.sqlitedb*` files.
