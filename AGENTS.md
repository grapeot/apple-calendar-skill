# Apple Calendar Skill

Read-only query CLI for the macOS Apple Calendar store (EventKit sqlite).

- Layout: `src/apple_calendar/` package (`timeutil.py` conversions,
  `store.py` discovery/snapshot/queries, `cli.py` commands) +
  `scripts/apple-calendar` thin launcher (runs from a checkout without
  installing). Also installable: `uv pip install -e '.[dev]'` provides the
  `apple-calendar` console script. Python 3.9+, stdlib only; `pytest` for
  the offline test suite.
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
- Tests: `pytest tests/` runs fully offline against a synthetic fixture
  store (discovered via the `APPLE_CALENDAR_STORE_DIR` env override); it
  never touches the live store. `selftest` (seven machine-checkable
  invariants) runs against whatever store the CLI is pointed at — run it on
  a real machine.
- `docs/working.md` is the project memory: record substantive changes under
  Changelog (dated bullets, one change each) and new pitfalls under Lessons
  Learned in the same change.
- Version control: only commit (or push/PR) when the user asks; keep commits
  small and reversible.
- Acceptance: `pytest tests/` all green, plus the spot cases in the
  "Acceptance" section of `skills/apple_calendar.md`.
- Pit log: P1–P6 incident table lives in the canonical skill doc; the
  `selftest` subcommand is the executable form of the invariants it encodes.