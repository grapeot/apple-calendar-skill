# Apple Calendar Skill

Read-only query CLI for the macOS Apple Calendar store (EventKit sqlite).

- Single file: `apple_calendar.py` — Python 3 stdlib only (sqlite3, zoneinfo).
  No venv, no dependencies; run with system `python3`.
- Hard boundary: **read-only by construction**. The live `Calendar.sqlitedb`
  is never opened; a snapshot copy (main + `-wal` + `-shm`) is read with
  `mode=ro`. No AppleScript, no EventKit, no mutation path of any kind.
- Skill doc (canonical): `skills/apple_calendar.md`.
- Time semantics (the reason this project exists): `start_date` / `end_date`
  are absolute seconds since `2001-01-01 00:00:00 UTC` (NSDate reference);
  `start_tz` is the original timezone for display only. All-day events store
  UTC midnight with tz `_float`. The CLI forces a dual representation
  (`start_utc` + `start_local`) so the misreading that produced a 7-hour
  error on 2026-10-13 cannot happen again.
- Acceptance: `python3 apple_calendar.py selftest` (machine-checkable
  invariants; exit 1 on failure) plus the spot cases in the "Acceptance"
  section of `skills/apple_calendar.md`.
- Pit log: P1–P6 incident table lives in the canonical skill doc; the
  `selftest` subcommand is the executable form of the invariants it encodes.
