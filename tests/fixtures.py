"""Shared synthetic store constants and CLI run helpers for offline tests."""
import contextlib
import datetime as dt
import io
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from apple_calendar import store

REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "scripts" / "apple-calendar"

_REF = dt.datetime(2001, 1, 1, tzinfo=dt.timezone.utc)


def ref_seconds(utc_dt: dt.datetime) -> float:
    """Store time-semantics: seconds since 2001-01-01T00:00:00Z."""
    return (utc_dt - _REF).total_seconds()


# A timed event stored at 2026-10-16T12:00:00Z (= 05:00 local PT), the same
# instant the real store keeps for the pre-order reminder.
TIMED_SD = ref_seconds(dt.datetime(2026, 10, 16, 12, 0, tzinfo=dt.timezone.utc))
TIMED_ED = TIMED_SD + 1800.0

# An all-day event dated 2026-11-03, stored at UTC midnight.
ALLDAY_SD = ref_seconds(dt.datetime(2026, 11, 3, 0, 0, tzinfo=dt.timezone.utc))
ALLDAY_ED = ALLDAY_SD + 86399.0

# A zero-duration reminder entry dated 2026-10-20.
ZERO_SD = ref_seconds(dt.datetime(2026, 10, 20, 12, 0, tzinfo=dt.timezone.utc))

UUID_TIMED = "11111111-1111-1111-1111-111111111111"

SCHEMA = """
CREATE TABLE Calendar (
  ROWID INTEGER PRIMARY KEY,
  title TEXT,
  type INTEGER,
  sharing_status INTEGER
);
CREATE TABLE CalendarItem (
  ROWID INTEGER PRIMARY KEY,
  UUID TEXT,
  summary TEXT,
  start_date REAL,
  start_tz TEXT,
  end_date REAL,
  end_tz TEXT,
  all_day INTEGER,
  description TEXT,
  has_recurrences INTEGER,
  last_modified REAL,
  calendar_id INTEGER
);
"""

FIXTURE_ROWS = [
    (
        1, UUID_TIMED, "Fixture Timed Event",
        TIMED_SD, "America/Los_Angeles", TIMED_ED, "America/Los_Angeles",
        0, "Sign in at apple.com to complete the pre-order.", 0,
        TIMED_SD, 11,
    ),
    (
        2, "22222222-2222-2222-2222-222222222222", "Fixture All Day Event",
        ALLDAY_SD, "_float", ALLDAY_ED, "_float",
        1, None, 0,
        ALLDAY_SD, 8,
    ),
    (
        3, "33333333-3333-3333-3333-333333333333", "Fixture Reminder",
        ZERO_SD, "America/Los_Angeles", ZERO_SD, "America/Los_Angeles",
        0, None, 1,
        ZERO_SD, 11,
    ),
]


def build_store(directory) -> Path:
    """Create the synthetic store; returns the db file path."""
    directory = Path(directory)
    db_path = directory / store.DB_NAME
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    con.execute(
        "INSERT INTO Calendar (ROWID, title, type, sharing_status) "
        "VALUES (11, 'Fixture Calendar', 1, 0)"
    )
    con.execute(
        "INSERT INTO Calendar (ROWID, title, type, sharing_status) "
        "VALUES (8, 'Fixture Holidays', 2, 0)"
    )
    con.executemany(
        "INSERT INTO CalendarItem (ROWID, UUID, summary, start_date, "
        "start_tz, end_date, end_tz, all_day, description, has_recurrences, "
        "last_modified, calendar_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        FIXTURE_ROWS,
    )
    con.commit()
    con.close()
    return db_path


def run_cli(args):
    """Run the CLI in-process; capture stdout/stderr and the exit code."""
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            from apple_calendar.cli import main
            main(args)
        except SystemExit as e:
            code = e.code or 0
    return code, out.getvalue(), err.getvalue()


def parse_json(stdout: str) -> dict:
    return json.loads(stdout)


def run_launcher(env_dir, args):
    """Run the thin launcher as a subprocess with the store override set."""
    env = dict(os.environ)
    env[store.STORE_DIR_ENV] = str(env_dir)
    return subprocess.run(
        [sys.executable, str(LAUNCHER)] + list(args),
        capture_output=True,
        text=True,
        env=env,
    )