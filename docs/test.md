# Test Strategy: Apple Calendar Skill

## Overview

The test architecture strictly isolates offline automated tests from live user calendar data. Tests verify pure time conversion logic, SQLite query predicates against synthetic fixtures, CLI subprocess contracts, and real-machine store invariants.

## Unit Tests (Pure Conversion Logic)

Located in `tests/test_apple_calendar.py`, focusing on pure functions in `timeutil.py`:
- **Epoch rules**: Conversion of Cocoa `NSDate` reference seconds (`2001-01-01T00:00:00Z`) to UTC ISO 8601 strings.
- **Wall-clock conversion**: Accurate formatting of UTC timestamps into local wall-clock representations matching `start_tz`.
- **Floating and unresolvable timezones**: All-day `_float` markers yield `null` local time; unknown timezones log warnings and fallback cleanly.
- **DST window behavior**: Verification that queries spanning Daylight Saving Time transitions preserve accurate local offsets.
- **Bad-date errors**: Validation of malformed date strings, raising clear descriptive errors.

## Integration Tests (Synthetic Fixture Store)

Execute against an in-memory/temporary SQLite database configured via `APPLE_CALENDAR_STORE_DIR`:
- **Window predicate regressions**: Confirm timed events match local day instant bounds and all-day events match UTC date strings, ensuring events on the day after `--end` are excluded.
- **Query operations**: Verify `calendars` output, `search` text filtering across summary/description/all fields, calendar title filtering, and `get` lookups by UUID or ROWID.
- **Selftest suite**: Assert green passing behavior against a compliant store, plus failure-injection tests verifying exit code `1` when invariants are breached (decoy store, negative duration, corrupted tz).
- **Launcher subprocess contract**: Invoke `scripts/apple-calendar` via subprocess, verifying exit codes (`0` success, `1` runtime error, `2` argument error), JSON envelope schema, and absence of raw Python tracebacks on stderr.

## On-Machine Tests (Host Verification)

CI environments (Ubuntu runners) lack macOS EventKit group containers and live stores, so CI runs offline tests only. On-machine verification acts as the live release gate on macOS:
- **Built-in Invariant Selftest**: Running `python3 scripts/apple-calendar selftest` checks seven invariants (`store_is_group_container`, `store_not_decoy`, `end_not_before_start`, `allday_tz_not_timezone`, `allday_stored_at_utc_midnight`, `local_zone_is_iana`, `display_roundtrip_sample`) against the active store.
- **Acceptance Spot Cases**: The four manual spot checks documented in `skills/apple_calendar.md` (iPhone pre-order UTC/local conversion, all-day float format, zero-result search, date boundary isolation).

## Verification Complete Definition

A change is verified complete when:
1. All 31 offline tests pass via `pytest tests/`.
2. The GitHub Actions CI workflow passes on Ubuntu.
3. `python3 scripts/apple-calendar selftest` exits with code `0` on a real macOS host.
4. The four canonical skill doc acceptance cases return matching results.
