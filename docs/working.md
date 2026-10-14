# Working Notes

## Changelog

### 2026-10-13 — Initial implementation

- Read-only CLI `apple_calendar.py` (Python 3 stdlib only): snapshots the
  EventKit store (`Calendar.sqlitedb` + `-wal` + `-shm` from the group
  container) into a temp directory and reads the copy with `mode=ro`. No
  write path of any kind.
- Subcommands: `calendars`, `list`, `search`, `get`, `selftest`. Exit codes:
  0 success, 1 error, 2 usage.
- Skill doc with the P1–P6 pit log and the absolute-instant time contract
  (`start_utc` is the source of truth, `start_local` is display only, the raw
  epoch column is never exposed, and every envelope restates the semantics in
  a `time_reference` field).
- `selftest`: seven machine-checkable store invariants.
- Repo scaffolding: MIT license, README, and a `.gitignore` that also blocks
  `*.sqlitedb*`.

An independent code and privacy review ran before the first merge; fixes
applied:

- `list` could pull in the all-day event on the day after `--end`; the
  instant-range window was replaced with a date-vs-instant predicate. A
  regression case was added to the skill doc's acceptance list.
- The duration invariant was too strict; corrected against observed data
  (`start == end` zero-duration entries are normal — 492 of 786 on the test
  store).
- Unified error handling and exit codes; snapshot retry on a torn copy; a
  stderr warning when the machine's IANA zone cannot be resolved.

### 2026-10-13 — Scaffold restructure + offline tests

- Restructured to the standard scaffold layout: `src/apple_calendar/` package
  (`timeutil.py`, `store.py`, `cli.py`), `scripts/apple-calendar` thin
  launcher, `pyproject.toml` (hatchling) with the `apple-calendar` console
  script, `.env.example`, root-level `apple_calendar.py` removed.
- Store discovery is overridable via the `APPLE_CALENDAR_STORE_DIR` env var
  so tests can point at a synthetic fixture store.
- 31 offline pytest tests against the synthetic store (reference-epoch
  conversions, wall-clock conversion, DST window behavior, list
  date-vs-instant window with regression cases, search/get/calendar filter,
  selftest green and failure-injection cases, launcher exit codes and clean
  error surface). No live store access.
- Minimal GitHub Actions CI (ubuntu, uv, pytest).
- Root-owned files inside the user's uv interpreter cache (written by a root
  uv run on ~Oct 7) broke `uv pip install`; cleaned via sudo after user
  confirmation, temporary `UV_CACHE_DIR` workaround removed.

## Lessons learned

- `start_date` / `end_date` are absolute seconds since the NSDate reference
  (`2001-01-01T00:00:00Z`); `start_tz` is display-only. Reading the stored
  instant as a wall-clock in that zone produced a 7-hour error.
- `~/Library/Calendars/Calendar.sqlitedb` is a 0-byte decoy. The live store
  is `~/Library/Group Containers/group.com.apple.calendar/Calendar.sqlitedb`,
  and recent writes live in its `-wal` sidecar — copy all three files.
- All-day events are date-only, stored at UTC midnight, and interleave in the
  same column with timed events of the previous local day; match them by
  date, never with an instant range.
- `datetime.now().astimezone().tzinfo` returns the current fixed offset, not
  a zone; resolve the IANA zone from `/etc/localtime` instead.
- AppleScript and pyobjc EventKit are TCC-gated for background processes
  (`-1743`); the snapshot path needs no permission.
- A file snapshot is not atomic; a concurrent WAL checkpoint can tear it, so
  opening the copy is retried once.
