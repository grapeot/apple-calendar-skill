# Product Requirements Document: Apple Calendar Query CLI

## Problem Statement

Automated coding and background agents running on macOS frequently need read access to the local Apple Calendar (`Calendar.app`) store to inspect upcoming schedules and check availability. However, accessing Calendar via AppleScript or EventKit APIs requires macOS Transparency, Consent, and Control (TCC) permissions, which are denied by default for non-interactive terminal processes and daemons (`-1743: Not authorized to send Apple events to Calendar`).

Additionally, the underlying EventKit SQLite store uses Cocoa's `NSDate` reference epoch (seconds since `2001-01-01T00:00:00Z`). On 2026-10-13, an agent misread a stored 12:00 UTC event as 12:00 local wall clock instead of 05:00 local, causing a 7-hour scheduling discrepancy. A reliable tool must guarantee permissionless read access and eliminate time-interpretation ambiguity.

## Users & Jobs to Be Done

- **Autonomous coding and background agents**: Inspect upcoming calendar events, search notes and titles, and verify free/busy intervals without GUI interruption or TCC permission prompts.
- **Machine owner**: Query personal schedules from the shell and verify store integrity using fast, deterministic, zero-install commands.

## Goals & Non-Goals

### Goals
- Provide permissionless, read-only calendar access that avoids the TCC automation gate.
- Enforce correct time semantics with dual UTC and local wall-clock outputs.
- Deliver a zero-dependency CLI executable directly from a repository checkout.
- Enable fully offline testing without accessing live personal calendar data.

### Non-Goals
- Write operations: creating, modifying, or deleting events or calendars.
- Recurrence expansion: calculating individual occurrences of recurring rule series.
- Extracting detailed alarms, attendees, or attachment payloads.
- Direct mutation of live SQLite stores or remote sync engine coordination.

## Requirements

1. **Discovery & Snapshot Read Path**: Locate the active group container database (`~/Library/Group Containers/group.com.apple.calendar/Calendar.sqlitedb`), copy it alongside its `-wal` and `-shm` sidecars to a temporary directory, and open it in read-only mode (`mode=ro`). Retry opening once if concurrent WAL checkpoints cause a torn read. Ignore the 0-byte decoy at `~/Library/Calendars/Calendar.sqlitedb`.
2. **Subcommands**:
   - `calendars`: List all configured accounts and calendars.
   - `list`: Query events across a local date range (`--start`, `--end`, optional `--calendar`).
   - `search`: Case-insensitive substring search (`--text`, optional `--field summary|description|all`).
   - `get`: Inspect single event by `--uuid` or `--rowid`.
   - `selftest`: Execute seven machine-checkable store invariants.
3. **Dual Time Representation**: Convert raw `NSDate` epoch seconds into authoritative ISO 8601 `start_utc`/`end_utc` and local `start_local`/`end_local` in original event timezone. Render all-day events at UTC midnight with timezone `_float`. Suppress raw epoch numbers and include a `time_reference` note in every JSON envelope.
4. **Testability & Store Override**: Support the `APPLE_CALENDAR_STORE_DIR` environment variable to redirect queries to synthetic fixture databases.
5. **Exit Codes & Errors**: Return exit code `0` on success, `1` on execution or invariant failure, and `2` on command-line usage errors.
6. **Platform & Portability**: Standard Python 3.9+ using only stdlib (`sqlite3`, `zoneinfo`). Offline test suite must run via `pytest` on Linux CI.

## Success Criteria

- All 31 offline tests pass in `tests/` without accessing live stores.
- Continuous integration runs green on Ubuntu runners.
- The `selftest` command reports 7/7 invariant checks passed on a real Mac.
- All four acceptance spot cases from the canonical skill doc pass verification.
