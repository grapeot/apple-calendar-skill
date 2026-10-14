"""Store discovery, snapshotting, and queries for the Apple Calendar store.

Read-only by construction: the live database is never opened. A snapshot
copy (main + `-wal` + `-shm`) is created in a temp directory and read with
`mode=ro`. All SQL issued by this module is SELECT.
"""
from __future__ import annotations

import datetime as dt
import os
import shutil
import sqlite3
import tempfile

from .timeutil import (
    EPOCH_OFFSET_1970,
    FLOAT_TZ_NAMES,
    REF_UTC,
    local_tz,
    utc_iso,
    wall_iso,
)

DB_NAME = "Calendar.sqlitedb"

DEFAULT_STORE_DIR = os.path.expanduser(
    "~/Library/Group Containers/group.com.apple.calendar"
)
# APPLE_CALENDAR_STORE_DIR overrides the store directory; used by tests to
# point discovery at a synthetic fixture store.
STORE_DIR_ENV = "APPLE_CALENDAR_STORE_DIR"

BASE_COLS = (
    "ci.ROWID, ci.UUID, ci.summary, ci.start_date, ci.start_tz, "
    "ci.end_date, ci.end_tz, ci.all_day, ci.description, "
    "ci.has_recurrences, ci.last_modified, c.title"
)
BASE_FROM = "FROM CalendarItem ci JOIN Calendar c ON ci.calendar_id = c.ROWID"


class CalendarError(RuntimeError):
    pass


def store_dir() -> str:
    override = os.environ.get(STORE_DIR_ENV, "").strip()
    if override:
        return override
    return DEFAULT_STORE_DIR


def using_default_store() -> bool:
    return not os.environ.get(STORE_DIR_ENV, "").strip()


def find_db() -> str:
    candidates = [store_dir()]
    p = os.path.join(candidates[0], DB_NAME)
    if os.path.isfile(p) and os.path.getsize(p) > 0:
        return p
    raise CalendarError(
        f"Calendar.sqlitedb not found (or empty) in: {candidates[0]} "
        f"(set {STORE_DIR_ENV} to override)"
    )


def snapshot(db_path: str) -> str:
    """Copy main db + WAL sidecars to a temp dir, preserving file names."""
    tmp = tempfile.mkdtemp(prefix="apple_calendar_")
    for suffix in ("", "-wal", "-shm"):
        src = db_path + suffix
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(tmp, DB_NAME + suffix))
    return tmp


def open_snapshot(tmp_dir: str) -> sqlite3.Connection:
    path = os.path.join(tmp_dir, DB_NAME)
    if not os.path.isfile(path):
        raise CalendarError("snapshot missing main db; store may be empty")
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def open_store():
    """Snapshot + open. Retry once: the three-file copy is not atomic, so a
    concurrent WAL checkpoint can tear the snapshot."""
    db_path = find_db()
    last: Exception | None = None
    for _ in range(2):
        tmp = snapshot(db_path)
        try:
            return db_path, tmp, open_snapshot(tmp)
        except sqlite3.Error as e:
            last = e
            shutil.rmtree(tmp, ignore_errors=True)
    raise last  # type: ignore[misc]


def row_to_event(r) -> dict:
    (rowid, uuid, summary, sd, stz, ed, etz, all_day, desc,
     has_rec, last_mod, cal) = r
    return {
        "rowid": rowid,
        "uuid": uuid,
        "summary": summary,
        "calendar": cal,
        "all_day": bool(all_day),
        "start_utc": utc_iso(sd),
        "end_utc": utc_iso(ed),
        "start_local": wall_iso(sd, stz),
        "end_local": wall_iso(ed, etz),
        "timezone": stz if stz and stz not in FLOAT_TZ_NAMES else "float",
        "description": desc,
        "has_recurrences": bool(has_rec),
        "last_modified_utc": utc_iso(last_mod),
    }