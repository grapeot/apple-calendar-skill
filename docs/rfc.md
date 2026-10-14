# RFC: Architecture and Design of Apple Calendar Query CLI

## Overview

`apple-calendar-skill` provides a fast, read-only interface to macOS Apple Calendar data. The implementation is organized into three distinct standard-library Python modules under `src/apple_calendar/`:
- `timeutil.py`: Pure, side-effect-free conversion logic between Cocoa `NSDate` epoch timestamps, UTC ISO 8601 strings, and local wall-clock times.
- `store.py`: Store discovery, snapshot management, SQLite schema queries, and invariant verification.
- `cli.py`: Command-line parsing, output envelope serialization, and standardized exit codes.

A thin executable script at `scripts/apple-calendar` adjusts `sys.path` and dispatches to `cli.py`, allowing zero-install invocation directly from a source checkout without requiring a virtual environment.

## The Snapshot Read Path

Official macOS automation routes (AppleScript and pyobjc EventKit bindings) fail in headless, daemon, or terminal contexts due to Transparency, Consent, and Control (TCC) permission gates (`-1743: Not authorized to send Apple events to Calendar`).

To provide reliable, non-interactive access, the tool bypasses TCC by copying the live EventKit SQLite database and its associated write-ahead log files (`Calendar.sqlitedb`, `Calendar.sqlitedb-wal`, and `Calendar.sqlitedb-shm`) into a temporary directory. The snapshot is opened with `sqlite3` in read-only URI mode (`file:...mode=ro`). Because concurrent SQLite checkpoints can modify sidecar files during file copying, snapshot opening catches operational errors and retries the copy operation once before failing.

## Key Architectural Decisions

### 1. Date-vs-Instant List Window
All-day events are stored at UTC midnight (`00:00:00Z`) with timezone `_float`. In timezones with negative UTC offsets, UTC midnight corresponds to the afternoon or evening of the preceding local date. As a result, all-day events interleave in the same timestamp column with timed events of the previous local calendar day. A naive single-instant range query either drops all-day events on the initial day or includes the all-day event for the day after `--end` (observed on 2026-10-13). The query resolves this by evaluating timed events against local day instant bounds while matching all-day events by their exact UTC date string.

### 2. Output Contract and Epoch Concealment
Apple Calendar stores seconds since `2001-01-01 00:00:00 UTC`. Exposing raw epoch seconds encourages agents and scripts to interpret values as Unix timestamps or local wall times, producing severe timing errors (such as the 7-hour discrepancy on 2026-10-13). The CLI conceals the raw epoch column entirely, emitting ISO 8601 `start_utc` (the authoritative source of truth) and `start_local` (formatted in the original timezone). Every JSON envelope embeds a `time_reference` field explaining the semantics to ensure the contract travels with the payload.

### 3. Machine Zone Resolved from /etc/localtime as IANA
Using `datetime.now().astimezone().tzinfo` returns a fixed offset representing current system time, which breaks query windows spanning Daylight Saving Time (DST) boundaries. The tool inspects the symlink target of `/etc/localtime` to extract the canonical IANA timezone name (e.g., `America/Los_Angeles`) and instantiates a `zoneinfo.ZoneInfo` object that accurately accounts for seasonal offset shifts.

### 4. Store Directory Override via APPLE_CALENDAR_STORE_DIR
To isolate tests from private user data and run CI on non-macOS environments, store discovery checks the `APPLE_CALENDAR_STORE_DIR` environment variable. When set, snapshot operations read from the specified directory instead of the system group container, providing a clean hook for synthetic test fixtures and offline backups.

### 5. Three-File Read-Only Snapshot and Decoy Avoidance
SQLite WAL mode stores uncheckpointed writes in `-wal` and `-shm` sidecar files; copying only `Calendar.sqlitedb` yields stale or incomplete state. The snapshot process explicitly copies all three files to a temporary directory. Additionally, macOS retains an obsolete 0-byte file at `~/Library/Calendars/Calendar.sqlitedb`. The tool strictly targets `~/Library/Group Containers/group.com.apple.calendar/Calendar.sqlitedb` and validates non-emptiness.

### 6. Zero-Dependency Standard Library Architecture
The core runtime relies solely on Python's built-in `sqlite3`, `zoneinfo`, `argparse`, `shutil`, and `tempfile` modules. Eliminating external dependencies guarantees instant startup, zero setup friction, and friction-free execution from terminal scripts or subagents.

## Alternatives Considered and Rejected

- **Direct SQLite writes to the live store**: Rejected. Modifying the live database bypasses the Apple sync engine (CalDAV, iCloud, Exchange), risking immediate database corruption, schema divergence, and silent synchronization conflicts.
- **AppleScript or pyobjc-EventKit APIs**: Rejected. These interfaces mandate interactive TCC authorization prompts, which fail with `-1743` in non-GUI terminal sessions and background agents.
- **Calendar.app GUI automation**: Rejected. Scripting UI interactions via Accessibility APIs is fragile, slow, and requires an unlocked graphical login session.

## Testing Strategy Summary

Testing follows a layered structure: pure unit tests verify `timeutil` conversions across edge cases; integration tests verify query predicates, CLI error handling, and launcher execution against synthetic SQLite stores via `APPLE_CALENDAR_STORE_DIR`; on-machine validation is executed via `selftest` against real macOS stores.

## Future Work

- **Write Operations**: Creating or modifying events requires a dedicated proposal incorporating CalDAV-safe change notifications, explicit calendar target selection, and interactive user confirmation gates.
- **Recurrence Expansion**: Parsing the `Recurrence` and `ExceptionDate` tables to expand recurring rule series into concrete individual occurrences.
