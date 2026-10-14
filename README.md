# Apple Calendar Skill

`apple-calendar-skill` is a read-only CLI tool for querying macOS Apple Calendar events directly from the local EventKit SQLite store. On modern macOS, accessing Calendar data via AppleScript or EventKit APIs requires Transparency, Consent, and Control (TCC) automation permissions that background agents and terminal processes are denied by default (`-1743: Not authorized to send Apple events to Calendar`). This tool avoids that permission entirely by taking a momentary file snapshot of `Calendar.sqlitedb` (along with its `-wal` and `-shm` sidecars) into a temporary directory and opening it in SQLite read-only mode (`mode=ro`), with no write path to the live store. It also guards against a subtle time-semantics trap where stored UTC instants are easily misread as local wall-clock values.

## Requirements

- macOS (to query the live Apple Calendar store)
- Python 3.9+
- Standard library only (`sqlite3`, `zoneinfo`) for runtime — no external dependencies or virtual environment required.
- `pytest>=8` (dev extra) only needed for running the offline test suite.

## Usage

The CLI can be executed directly from a repository checkout without installation via the launcher script:

```bash
python3 scripts/apple-calendar <subcommand>
```

Alternatively, install the package in development mode to use the `apple-calendar` console script:

```bash
pip install -e .
apple-calendar <subcommand>
```

All subcommands emit structured JSON to stdout. Exit codes are `0` on success, `1` on error, and `2` on command-line usage error.

To point the tool at an alternate store directory or test fixture instead of the default group container, set the `APPLE_CALENDAR_STORE_DIR` environment variable.

### List Calendars

List all available calendars and accounts:

```bash
python3 scripts/apple-calendar calendars
```

### List Events

List events within a date range specified as local calendar dates (`YYYY-MM-DD`). Timed events are matched by instant inside those local days, while all-day events are matched by their UTC date:

```bash
python3 scripts/apple-calendar list --start 2026-10-01 --end 2026-10-31
python3 scripts/apple-calendar list --start 2026-10-01 --end 2026-10-31 --calendar "Personal"
```

If omitted, `--start` and `--end` default to today through today+60 days (inclusive).

### Search Events

Perform a case-insensitive substring search over event summaries and descriptions:

```bash
python3 scripts/apple-calendar search --text iphone
python3 scripts/apple-calendar search --text renewal --field description
```

The `--field` flag accepts `summary`, `description`, or `all` (default: `all`).

### Get Event

Fetch full details for an event by UUID or ROWID:

```bash
python3 scripts/apple-calendar get --uuid <uuid>
python3 scripts/apple-calendar get --rowid 42
```

### Run Selftest

Run the built-in invariant test suite:

```bash
python3 scripts/apple-calendar selftest
```

## Testing

Run the offline unit and integration test suite:

```bash
pytest tests/
```

To verify store identity and time-semantics invariants on a real Mac:

```bash
python3 scripts/apple-calendar selftest
```

## Time Semantics

The SQLite database backing Apple Calendar stores timestamps using Cocoa's `NSDate` reference convention, which is prone to misinterpretation:

- **Absolute instants**: The `start_date` and `end_date` columns store absolute seconds since `2001-01-01 00:00:00 UTC` (the `NSDate` reference epoch), not wall-clock values. Treating them as local wall-clock values in `start_tz` causes severe time-shift errors (such as an incident on 2026-10-13 where a 12:00 UTC event was misread as 12:00 local instead of 05:00 local).
- **Timezone handling**: The `start_tz` and `end_tz` columns record the event's original timezone and are used strictly to render local wall-clock display times.
- **All-day events**: All-day items have `all_day = 1`, timezone `_float`, and are stored at UTC midnight (`00:00:00Z`) of the event date.
- **Output contract**: The tool never exposes the raw epoch columns. Output always provides `start_utc` / `end_utc` (the authoritative source of truth in ISO 8601 UTC) alongside `start_local` / `end_local` (wall-clock time in the original timezone, or `null` for float/all-day events). Every JSON envelope carries a `time_reference` note explaining these rules.
- **Zero-duration entries**: Events where `start_date == end_date` are normal reminder-like items in Apple Calendar. The store invariant is `end >= start`, never `end < start`.

## Limitations

- **Recurring series**: Recurring events only flag `has_recurrences: true`; individual recurrence rule occurrences and exception dates are not expanded.
- **Event detail**: Alarms, attendees, and attachments are not exposed.
- **Unified store**: All accounts configured in Calendar (iCloud, Google, Exchange, local) share a single SQLite database; use the `calendar` field to distinguish them.
- **Snapshot isolation**: Queries run against a moment-in-time snapshot. If Calendar.app was mid-write when the snapshot was taken, re-running may be required.

## License

MIT
