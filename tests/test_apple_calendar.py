"""Offline tests for the apple_calendar CLI (synthetic store, no live data).

The time-semantics invariants are the core of what these tests lock down:
absolute instants since the NSDate reference, all-day events as UTC-midnight
dates, and the date-vs-instant list window that keeps neighbor-day all-day
events out.
"""
import datetime as dt
import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from apple_calendar import store, timeutil
from fixtures import (
    ALLDAY_SD,
    UUID_TIMED,
    parse_json,
    run_cli,
    run_launcher,
)

REF = timeutil.REF_UTC


# ---------------------------------------------------------------------------
# pure time conversions (no store I/O)
# ---------------------------------------------------------------------------

def test_reference_epoch_is_nsdate():
    assert REF == dt.datetime(2001, 1, 1, tzinfo=dt.timezone.utc)


def test_secs_to_utc_matches_known_instant():
    assert timeutil.secs_to_utc(813844800.0) == dt.datetime(
        2026, 10, 16, 12, 0, tzinfo=dt.timezone.utc
    )
    assert timeutil.utc_iso(813844800.0) == "2026-10-16T12:00:00Z"


def test_epoch_offset_1970_constant():
    unix = (
        dt.datetime(2001, 1, 1, tzinfo=dt.timezone.utc)
        - dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
    ).total_seconds()
    assert timeutil.EPOCH_OFFSET_1970 == unix


def test_wall_converts_instant_to_original_timezone():
    ts = 813844800.0
    assert timeutil.wall_iso(ts, "America/Los_Angeles") == (
        "2026-10-16T05:00:00-07:00"
    )
    assert timeutil.wall_iso(ts, "UTC") == "2026-10-16T12:00:00+00:00"


def test_wall_returns_none_for_float_and_unresolvable():
    ts = 813844800.0
    assert timeutil.wall_iso(ts, "_float") is None
    assert timeutil.wall_iso(ts, "") is None
    assert timeutil.wall_iso(ts, "Not/AZone") is None
    assert timeutil.wall_iso(None, "America/Los_Angeles") is None


def test_local_tz_resolves_iana_zone():
    tz = timeutil.local_tz()
    assert isinstance(tz, ZoneInfo)


def test_local_date_window_handles_dst():
    # Local midnights differ across DST: a fixed-offset tzinfo would render
    # January and July midnights with the same offset.
    local_name = timeutil.local_tz()
    jan = dt.datetime.fromtimestamp(
        timeutil.local_date_to_utc_seconds("2026-01-01", False), dt.timezone.utc
    ).astimezone(local_name)
    jul = dt.datetime.fromtimestamp(
        timeutil.local_date_to_utc_seconds("2026-07-01", False), dt.timezone.utc
    ).astimezone(local_name)
    if jan.utcoffset() == jul.utcoffset():
        pytest.skip(f"zone {local_name} has no DST in 2026")


def test_bad_date_raises_value_error():
    with pytest.raises(ValueError):
        timeutil.local_date_to_utc_seconds("2026-13-99", False)


# ---------------------------------------------------------------------------
# store discovery (fixture store via env override)
# ---------------------------------------------------------------------------

def test_store_dir_env_override(store_dir):
    assert store.using_default_store() is False
    assert store.store_dir() == str(store_dir)
    assert store.find_db() == str(store_dir / store.DB_NAME)


def test_find_db_rejects_missing_store(tmp_path, monkeypatch):
    monkeypatch.setenv(store.STORE_DIR_ENV, str(tmp_path))
    with pytest.raises(store.CalendarError):
        store.find_db()


def test_find_db_rejects_zero_byte_store(tmp_path, monkeypatch):
    (tmp_path / store.DB_NAME).touch()
    monkeypatch.setenv(store.STORE_DIR_ENV, str(tmp_path))
    with pytest.raises(store.CalendarError):
        store.find_db()


def test_default_store_points_at_group_container():
    assert "Group Containers/group.com.apple.calendar" in store.DEFAULT_STORE_DIR


def test_snapshot_copies_wal_sidecars(store_dir):
    db_path = store.find_db()
    (store_dir / (store.DB_NAME + "-wal")).write_bytes(b"wal-bytes")
    tmp = Path(store.snapshot(str(db_path)))
    try:
        assert (tmp / store.DB_NAME).exists()
        assert (tmp / (store.DB_NAME + "-wal")).read_bytes() == b"wal-bytes"
    finally:
        store.shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# CLI commands against the fixture store
# ---------------------------------------------------------------------------

def test_list_includes_timed_event_by_instant(store_dir):
    code, out, err = run_cli(["list", "--start", "2026-10-16", "--end", "2026-10-16"])
    assert code == 0, err
    data = parse_json(out)
    assert data["count"] == 1
    event = data["events"][0]
    assert event["summary"] == "Fixture Timed Event"
    assert event["start_utc"] == "2026-10-16T12:00:00Z"
    assert event["start_local"] == "2026-10-16T05:00:00-07:00"
    assert event["all_day"] is False
    assert "time_reference" in data


def test_list_excludes_next_day_allday(store_dir):
    # Regression: an all-day event on the day after --end must not leak in.
    code, out, err = run_cli(["list", "--start", "2026-11-01", "--end", "2026-11-02"])
    assert code == 0, err
    assert parse_json(out)["count"] == 0


def test_list_includes_allday_event_on_its_date(store_dir):
    # An all-day event is stored at UTC midnight, which is BEFORE the local
    # midnight of its own display date on west-of-UTC machines; matching by
    # instant would miss it. Matching by UTC date must find it.
    code, out, err = run_cli(["list", "--start", "2026-11-03", "--end", "2026-11-03"])
    assert code == 0, err
    data = parse_json(out)
    assert data["count"] == 1
    event = data["events"][0]
    assert event["all_day"] is True
    assert event["timezone"] == "float"
    assert event["start_utc"] == "2026-11-03T00:00:00Z"
    assert event["start_local"] is None


def test_list_calendar_filter(store_dir):
    code, out, err = run_cli(
        ["list", "--start", "2026-10-01", "--end", "2026-12-31",
         "--calendar", "Fixture Holidays"]
    )
    assert code == 0, err
    data = parse_json(out)
    assert data["count"] == 1
    assert data["events"][0]["calendar"] == "Fixture Holidays"


def test_list_zero_duration_entry_is_included(store_dir):
    code, out, err = run_cli(["list", "--start", "2026-10-20", "--end", "2026-10-20"])
    assert code == 0, err
    data = parse_json(out)
    assert data["count"] == 1
    event = data["events"][0]
    assert event["start_utc"] == event["end_utc"]


def test_search_summary_and_description(store_dir):
    code, out, _ = run_cli(["search", "--text", "fixture timed"])
    assert code == 0
    assert parse_json(out)["count"] == 1

    code, out, _ = run_cli(
        ["search", "--text", "pre-order", "--field", "description"]
    )
    assert code == 0
    assert parse_json(out)["count"] == 1

    code, out, _ = run_cli(["search", "--text", "duo"])
    assert code == 0
    assert parse_json(out)["count"] == 0


def test_get_by_uuid(store_dir):
    code, out, err = run_cli(["get", "--uuid", UUID_TIMED])
    assert code == 0, err
    data = parse_json(out)
    assert data["event"]["summary"] == "Fixture Timed Event"
    assert data["event"]["rowid"] == 1


def test_get_with_both_identifiers_is_error(store_dir):
    code, out, err = run_cli(["get", "--uuid", UUID_TIMED, "--rowid", "2"])
    assert code == 1
    assert "not both" in err


def test_get_requires_identifier(store_dir):
    code, out, err = run_cli(["get"])
    assert code == 1


def test_get_missing_event(store_dir):
    code, out, err = run_cli(["get", "--uuid", "does-not-exist"])
    assert code == 1
    assert "not found" in err


def test_calendars_lists_titles(store_dir):
    code, out, err = run_cli(["calendars"])
    assert code == 0, err
    titles = [c["title"] for c in parse_json(out)["calendars"]]
    assert "Fixture Calendar" in titles
    assert "Fixture Holidays" in titles


def test_selftest_green_on_fixture_store(store_dir):
    code, out, err = run_cli(["selftest"])
    assert code == 0, err
    data = parse_json(out)
    assert data["all_ok"] is True
    assert [c for c in data["selftest"] if not c["ok"]] == []


def insert_row(store_dir, rowid, uuid, summary, sd, stz, ed, etz,
               all_day, cal_id):
    con = sqlite3.connect(store_dir / store.DB_NAME)
    con.execute(
        "INSERT INTO CalendarItem (ROWID, UUID, summary, start_date, "
        "start_tz, end_date, end_tz, all_day, description, has_recurrences, "
        "last_modified, calendar_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, ?, ?)",
        (rowid, uuid, summary, sd, stz, ed, etz, all_day, ed, cal_id),
    )
    con.commit()
    con.close()


def test_selftest_flags_end_before_start(store_dir):
    insert_row(
        store_dir, 9, "99999999-9999-9999-9999-999999999999", "Backwards",
        880000000.0, "America/Los_Angeles", 870000000.0, "America/Los_Angeles",
        0, 11,
    )
    code, out, err = run_cli(["selftest"])
    assert code == 1, err
    data = parse_json(out)
    assert data["all_ok"] is False
    failed = [c["check"] for c in data["selftest"] if not c["ok"]]
    assert failed == ["end_not_before_start"]


def test_selftest_flags_allday_not_at_utc_midnight(store_dir):
    insert_row(
        store_dir, 8, "88888888-8888-8888-8888-888888888888", "Wrong Shape",
        ALLDAY_SD + 800.0, "_float", ALLDAY_SD + 1000.0, "_float", 1, 8,
    )
    code, out, err = run_cli(["selftest"])
    assert code == 1, err
    checks = {c["check"]: c["ok"] for c in parse_json(out)["selftest"]}
    assert checks["allday_stored_at_utc_midnight"] is False


# ---------------------------------------------------------------------------
# subprocess-level contract (thin launcher, exit codes, clean error surface)
# ---------------------------------------------------------------------------

def test_launcher_json_contract(store_dir):
    proc = run_launcher(store_dir, ["search", "--text", "fixture"])
    assert proc.returncode == 0, proc.stderr
    assert "time_reference" in proc.stdout


def test_launcher_clean_error_on_bad_date(store_dir):
    proc = run_launcher(store_dir, ["list", "--start", "2026-13-99"])
    assert proc.returncode == 1
    assert "Traceback" not in proc.stderr
    assert proc.stderr.startswith("apple_calendar:")


def test_launcher_usage_error_code(store_dir):
    proc = run_launcher(store_dir, ["search", "--text", "x", "--field", "nope"])
    assert proc.returncode == 2


def test_launcher_missing_store_fails_cleanly(tmp_path, monkeypatch):
    empty = tmp_path / "no-store-here"
    empty.mkdir()
    proc = run_launcher(empty, ["list"])
    assert proc.returncode == 1
    assert "Traceback" not in proc.stderr
    assert "Calendar.sqlitedb not found" in proc.stderr