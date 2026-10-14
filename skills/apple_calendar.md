---
name: apple-calendar
description: >-
  Read-only queries against the macOS Apple Calendar (EventKit sqlite) store
  for listing, searching, and inspecting events, with the time-semantics traps
  documented. Read-only by construction.
disable-model-invocation: true
---

# Apple Calendar Skill (Read-Only)

## When to use

The agent needs to read Apple Calendar (the Mac `Calendar.app` store): list
events in a range, search by text, or inspect one event. Trigger words:
"apple calendar", "mac calendar", "苹果日历", "查日历事件".

## Hard boundary

Read-only by construction. The tool never opens the live database, never
writes to the group container, and has no AppleScript / EventKit / SQL-write
path. Creating, editing, or deleting events is out of scope for this skill
and would need its own design plus explicit user approval.

## Pit log (read first — these are real incidents, 2026-10-13 session)

| # | Pit | Consequence that actually happened | Standing rule |
|---|-----|---|---|
| P1 | `start_date` read as a wall-clock in `start_tz` | iPhone pre-order read as "12:00 PT" when the stored instant was 12:00 UTC = 05:00 PT (a 7h error) | Act only on `*_utc`. `start_local` is display-only. The CLI deliberately does not expose the raw epoch column — do not add it |
| P2 | `~/Library/Calendars/Calendar.sqlitedb` is a 0-byte decoy | Copying it silently yields empty queries; a wrong "no such event" conclusion was almost drawn | The store is ONLY the group-container path; `selftest` asserts identity + non-emptiness |
| P3 | AppleScript / pyobjc-EventKit are TCC-denied (`-1743`) | Time burned on an automation path that cannot work from this process tree | Do not retry the automation path; the sqlite snapshot is the only no-permission route |
| P4 | Uncheckpointed writes live in `-wal`/`-shm` | A main-file-only copy can read stale data | Always snapshot all three files (the CLI does this) |
| P5 | All-day events are date-only and stored at UTC midnight, so they interleave in the same column with timed events of the previous local day | A naive single-instant window either misses the all-day event on the first day or pulls in the all-day event on the day after `--end` (observed 2026-10-13) | Match timed events by instant and all-day events by their UTC date; do not build the window as one instant range |
| P6 | `now().astimezone().tzinfo` is the CURRENT fixed offset, not a zone | List windows crossing DST were off by 1h (caught in review, 2026-10-13) | Resolve the IANA zone from `/etc/localtime`; `selftest` asserts a `ZoneInfo` result |

Run `selftest` after any change to this tool, and before trusting output that
looks inconsistent. A `selftest` failure means re-derive the time semantics
from primary data (multiple events, known instants) before acting.

## Data source

- Live store: `~/Library/Group Containers/group.com.apple.calendar/Calendar.sqlitedb`
  (EventKit store). `-wal` / `-shm` sidecars hold uncheckpointed writes (P4).
- **DECOY:** `~/Library/Calendars/Calendar.sqlitedb` is a 0-byte file on
  current macOS (P2). Do not use it.

Why not AppleScript or pyobjc/EventKit: both go through macOS TCC and are
denied for this process (`-1743: Not authorized to send Apple events to
Calendar`) (P3). The sqlite snapshot path needs no special permission.

## Snapshot procedure (what the CLI does)

1. Copy `Calendar.sqlitedb` + `-wal` + `-shm` (if present) to a temp dir,
   preserving file names.
2. Open the copy with `sqlite3` in `mode=ro`.
3. Query and print JSON. The live files are never touched.

Caveat: the snapshot is a moment-in-time copy. If Calendar.app was mid-write,
a field may be stale; re-run if results look inconsistent.

## Time semantics (the core trap behind P1)

- `start_date` / `end_date` are **absolute instants**: seconds since
  `2001-01-01 00:00:00 UTC` (the NSDate reference). Not wall-clock values.
- `start_tz` / `end_tz` hold the event's **original timezone**, for rendering
  wall-clock time only.
- All-day events: `all_day = 1`, tz column `_float`, stored at UTC midnight
  of the event date (P5).
- Zero-duration entries (start_date == end_date) are normal in this store —
  they are reminder-like items; 492 of 786 items observed on 2026-10-13.
  The invariant is end >= start, never end < start.
- Corroborating data points: the 2023 / 2024 / 2026 "Your iPhone Pre-order"
  reminders are all stored at 12:00 UTC (= 05:00 local, Apple's standard
  pre-order opening); all-day holidays sit at UTC midnight.
- The CLI makes the right reading the only reading: output carries
  `start_utc` (source of truth) + `start_local` (display) and never the raw
  epoch column. The envelope's `time_reference` field restates this in every
  response so the semantics travel with the data.

## CLI

Single-file stdlib CLI (sqlite3 + zoneinfo only); no venv needed, run with
system `python3`:

```bash
python3 apple_calendar.py calendars
python3 apple_calendar.py list --start 2026-10-01 --end 2026-10-31 [--calendar <title>]
python3 apple_calendar.py search --text iphone
python3 apple_calendar.py search --text renewal --field description
python3 apple_calendar.py get --uuid <uuid>
python3 apple_calendar.py get --rowid 1133
python3 apple_calendar.py selftest
```

- `list` `--start` / `--end` bounds are local calendar dates (default: today
  through today+60 days, inclusive); timed events are matched by instant inside
  those local days, all-day events by their UTC date; therefore an all-day event
  on the day after `--end` does not appear.
- `search` is case-insensitive substring over summary and/or description
  (`--field summary|description|all`, default `all`).
- `get` returns the full event; `--uuid` or `--rowid`.
- `selftest` runs seven invariant checks (store identity and non-decoy, all-day
  shape, `end >= start`, IANA zone resolution, and a non-empty display
  round-trip sample) and exits 1 on any failure.
- Exit codes: 0 success, 1 error, 2 usage.

## Output contract

Envelope: `{tool, db, snapshot_at, time_reference, count, events}` (or
`calendars` / `event` / `selftest`). Each event:

| Field | Meaning |
|---|---|
| `rowid` / `uuid` | store identifiers (uuid is stable across queries) |
| `summary`, `calendar`, `description` | event fields; `calendar` disambiguates accounts |
| `all_day` | boolean |
| `start_utc` / `end_utc` | absolute instants, `YYYY-MM-DDTHH:MM:SSZ` — **source of truth** |
| `start_local` / `end_local` | wall-clock in the event's original timezone with offset; `null` for float/all-day or unresolvable zones |
| `timezone` | original timezone, or `float` |
| `has_recurrences` | boolean flag; occurrences are NOT expanded |
| `last_modified_utc` | store-level modification instant |

## Quoting event times back to the user

- Prefer `start_local` (the user's wall clock) when telling the user a time,
  but derive it from `start_utc`; never quote the raw epoch column.
- When converting an event time for any other purpose, show both
  representations (e.g. the 2026 pre-order: 12:00 UTC = 05:00 PT) and check
  the conversion back.

## Known limits

- Recurring series: `has_recurrences` flag only; individual occurrences are
  not expanded (Recurrence / ExceptionDate tables exist but are unhandled).
- No alarm, attendee, or attachment details.
- All accounts (iCloud, local, subscribed) merge into one store; use the
  `calendar` field to tell them apart.
- Snapshot semantics as above.

## Acceptance (executed form: `selftest`; spot cases below)

1. `list --start 2026-10-01 --end 2026-12-31` → "Your iPhone Pre-order" with
   `start_utc: 2026-10-16T12:00:00Z` and `start_local:
   2026-10-16T05:00:00-07:00`.
2. Any all-day event (e.g. Election Day 2026-11-03) → `all_day: true`,
   `timezone: float`, `start_utc` ending in `T00:00:00Z`.
3. `search --text duo` → `count: 0`.
4. `list --start 2026-11-01 --end 2026-11-02` must return `count: 0` (the
   all-day event on 2026-11-03 must not leak in).
