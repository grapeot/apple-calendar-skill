#!/usr/bin/env python3
"""apple_calendar — read-only query CLI for the macOS Apple Calendar store.

Reads a read-only snapshot of Calendar.sqlitedb (the EventKit store) and
prints JSON. Read-only by construction: the live database is never opened
and no mutation path (AppleScript/EventKit/SQL write) exists in this tool.

Time semantics (critical):
  start_date / end_date are ABSOLUTE instants: seconds since
  2001-01-01 00:00:00 UTC (the NSDate reference). They are NOT wall-clock
  values. start_tz / end_tz hold the event's ORIGINAL timezone, used only to
  render wall-clock time. All-day events: all_day=1, tz column is '_float',
  stored at UTC midnight of the event date.
  Never interpret start_date as a wall-clock time in start_tz.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from zoneinfo import ZoneInfo

DB_NAME = "Calendar.sqlitedb"
STORE_DIRS = [
    os.path.expanduser(
        "~/Library/Group Containers/group.com.apple.calendar"
    ),
]
# ~/Library/Calendars/Calendar.sqlitedb is a 0-byte decoy on current macOS.

REF_UTC = dt.datetime(2001, 1, 1, tzinfo=dt.timezone.utc)

# 2001-01-01T00:00:00Z expressed in 1970-unix seconds; used to hand sqlite a
# real unix timestamp for date()/strftime() on stored reference-date values.
EPOCH_OFFSET_1970 = 978307200

BASE_COLS = (
    "ci.ROWID, ci.UUID, ci.summary, ci.start_date, ci.start_tz, "
    "ci.end_date, ci.end_tz, ci.all_day, ci.description, "
    "ci.has_recurrences, ci.last_modified, c.title"
)
BASE_FROM = "FROM CalendarItem ci JOIN Calendar c ON ci.calendar_id = c.ROWID"


class CalendarError(RuntimeError):
    pass


def fail(msg: str) -> None:
    print(f"apple_calendar: {msg}", file=sys.stderr)
    sys.exit(1)


def find_db() -> str:
    for d in STORE_DIRS:
        p = os.path.join(d, DB_NAME)
        if os.path.isfile(p) and os.path.getsize(p) > 0:
            return p
    raise CalendarError(
        "Calendar.sqlitedb not found in: " + ", ".join(STORE_DIRS)
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


def secs_to_utc(ts) -> dt.datetime | None:
    if ts is None:
        return None
    return REF_UTC + dt.timedelta(seconds=float(ts))


def utc_iso(ts) -> str | None:
    d = secs_to_utc(ts)
    return d.strftime("%Y-%m-%dT%H:%M:%SZ") if d is not None else None


def wall_iso(ts, tz_name) -> str | None:
    d = secs_to_utc(ts)
    if d is None or not tz_name or tz_name in ("_float", "float"):
        return None
    try:
        zi = ZoneInfo(tz_name)
    except Exception:
        return None
    return d.astimezone(zi).isoformat()


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
        "timezone": stz if stz and stz not in ("_float", "float") else "float",
        "description": desc,
        "has_recurrences": bool(has_rec),
        "last_modified_utc": utc_iso(last_mod),
    }


def local_tz() -> dt.tzinfo:
    """The machine's IANA zone (DST-correct for any target date).

    `datetime.now().astimezone().tzinfo` returns the CURRENT fixed offset,
    which misplaces events by 1h in list windows that cross DST.
    """
    try:
        link = os.path.realpath("/etc/localtime")
        marker = "/zoneinfo/"
        i = link.rfind(marker)
        if i != -1:
            return ZoneInfo(link[i + len(marker):])
    except Exception:
        pass
    print(
        "apple_calendar: warning: cannot resolve the machine's IANA zone from "
        "/etc/localtime; falling back to the current fixed UTC offset, so "
        "list windows crossing DST may be off by 1h",
        file=sys.stderr,
    )
    return dt.datetime.now().astimezone().tzinfo


def local_date_to_utc_seconds(date_str: str, end_of_day: bool) -> float:
    d = dt.date.fromisoformat(date_str)
    tz = local_tz()
    hh, mm, ss = (23, 59, 59) if end_of_day else (0, 0, 0)
    wall = dt.datetime(d.year, d.month, d.day, hh, mm, ss, tzinfo=tz)
    return (wall - REF_UTC).total_seconds()


def emit(payload: dict, db_path: str) -> None:
    payload = {
        "tool": "apple_calendar",
        "db": db_path,
        "snapshot_at": dt.datetime.now(dt.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "time_reference": (
            "start_date/end_date in the store are absolute seconds since "
            "2001-01-01T00:00:00Z; *_utc fields below are the source of "
            "truth, *_local is display-only"
        ),
        **payload,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def cmd_calendars(args, con, db_path) -> None:
    rows = con.execute(
        "SELECT ROWID, title, type, sharing_status FROM Calendar "
        "ORDER BY ROWID"
    ).fetchall()
    calendars = [
        {
            "rowid": r[0],
            "title": r[1],
            "type": r[2],
            "sharing_status": r[3],
        }
        for r in rows
    ]
    emit({"count": len(calendars), "calendars": calendars}, db_path)


def cmd_list(args, con, db_path) -> None:
    # Timed events are matched by instant inside the local-day window. All-day
    # events are date-only, stored at UTC midnight, and interleave in the same
    # column with timed events of the previous local day, so no single instant
    # range can separate them; match them by their UTC date instead.
    lo = local_date_to_utc_seconds(args.start, end_of_day=False)
    hi = local_date_to_utc_seconds(args.end, end_of_day=True)
    sql = (
        f"SELECT {BASE_COLS} {BASE_FROM} WHERE ("
        "(ci.all_day = 0 AND ci.start_date BETWEEN ? AND ?) OR "
        "(ci.all_day = 1 AND "
        f"date(ci.start_date + {EPOCH_OFFSET_1970}, 'unixepoch') "
        "BETWEEN ? AND ?))"
    )
    params: list = [lo, hi, args.start, args.end]
    if args.calendar:
        sql += " AND lower(c.title) = lower(?)"
        params.append(args.calendar)
    sql += " ORDER BY ci.start_date, ci.ROWID"
    rows = con.execute(sql, params).fetchall()
    events = [row_to_event(r) for r in rows]
    emit({"count": len(events), "events": events}, db_path)


def cmd_search(args, con, db_path) -> None:
    conds = []
    params: list = []
    like = f"%{args.text.lower()}%"
    if args.field in ("summary", "all"):
        conds.append("lower(ci.summary) LIKE ?")
        params.append(like)
    if args.field in ("description", "all"):
        conds.append("lower(coalesce(ci.description, '')) LIKE ?")
        params.append(like)
    sql = (
        f"SELECT {BASE_COLS} {BASE_FROM} "
        "WHERE " + " OR ".join(conds) + " ORDER BY ci.start_date, ci.ROWID"
    )
    rows = con.execute(sql, params).fetchall()
    events = [row_to_event(r) for r in rows]
    emit({"query": args.text, "count": len(events), "events": events}, db_path)


def cmd_get(args, con, db_path) -> None:
    if args.uuid and args.rowid is not None:
        fail("get takes either --uuid or --rowid, not both")
    if args.uuid:
        sql = f"SELECT {BASE_COLS} {BASE_FROM} WHERE ci.UUID = ?"
        params = [args.uuid]
    elif args.rowid is not None:
        sql = f"SELECT {BASE_COLS} {BASE_FROM} WHERE ci.ROWID = ?"
        params = [args.rowid]
    else:
        fail("get requires --uuid or --rowid")
    row = con.execute(sql, params).fetchone()
    if row is None:
        fail("event not found")
    emit({"event": row_to_event(row)}, db_path)


def cmd_selftest(args, con, db_path) -> None:
    """Machine-checkable invariants of the store's time semantics.

    Any failure means: do not trust output from this store until the time
    semantics are re-examined from primary data.
    """
    checks = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    add(
        "store_is_group_container",
        "/Group Containers/group.com.apple.calendar/" in db_path,
        db_path,
    )
    size = os.path.getsize(db_path)
    add("store_not_decoy", size > 0, f"{size} bytes")

    # Zero-duration entries (start_date == end_date) are normal in this store
    # (reminder-like items; 492/786 observed 2026-10-13). Only end < start is
    # a real violation.
    bad = con.execute(
        "SELECT COUNT(*) FROM CalendarItem "
        "WHERE start_date IS NOT NULL AND end_date IS NOT NULL "
        "AND end_date < start_date"
    ).fetchone()[0]
    zero = con.execute(
        "SELECT COUNT(*) FROM CalendarItem WHERE start_date = end_date"
    ).fetchone()[0]
    add("end_not_before_start", bad == 0,
        f"violations={bad}; zero_duration={zero} (normal)")

    bad = con.execute(
        "SELECT COUNT(*) FROM CalendarItem WHERE all_day = 1 "
        "AND start_tz IS NOT NULL AND start_tz NOT IN ('_float', 'float')"
    ).fetchone()[0]
    add("allday_tz_not_timezone", bad == 0,
        f"violations={bad} (float or NULL required)")

    bad = con.execute(
        "SELECT COUNT(*) FROM CalendarItem WHERE all_day = 1 AND "
        f"strftime('%H:%M:%S', start_date + {EPOCH_OFFSET_1970}, 'unixepoch') "
        "<> '00:00:00'"
    ).fetchone()[0]
    add("allday_stored_at_utc_midnight", bad == 0, f"violations={bad}")

    tz = local_tz()
    add("local_zone_is_iana", isinstance(tz, ZoneInfo), f"resolved={tz!r}")

    mismatches = 0
    sample = 0
    for sd, stz in con.execute(
        "SELECT start_date, start_tz FROM CalendarItem "
        "WHERE all_day = 0 AND start_date IS NOT NULL "
        "AND start_tz IS NOT NULL AND start_tz NOT IN ('_float', 'float') "
        "LIMIT 200"
    ):
        sample += 1
        w = wall_iso(sd, stz)
        if w is None:
            mismatches += 1
            continue
        if abs(
            (dt.datetime.fromisoformat(w) - secs_to_utc(sd)).total_seconds()
        ) > 0.5:
            mismatches += 1
    add("display_roundtrip_sample", mismatches == 0 and sample > 0,
        f"mismatches={mismatches}/{sample}" +
        (" (no timed events sampled)" if sample == 0 else ""))

    all_ok = all(c["ok"] for c in checks)
    emit({"selftest": checks, "all_ok": all_ok}, db_path)
    if not all_ok:
        sys.exit(1)


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


def main() -> None:
    p = argparse.ArgumentParser(
        prog="apple_calendar",
        description="Read-only queries against the macOS Apple Calendar store.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("calendars", help="list calendars")
    sp.set_defaults(fn=cmd_calendars)

    sp = sub.add_parser("list", help="list events in a date range")
    sp.add_argument("--start", default=dt.date.today().isoformat())
    sp.add_argument(
        "--end",
        default=(dt.date.today() + dt.timedelta(days=60)).isoformat(),
    )
    sp.add_argument("--calendar", default=None)
    sp.set_defaults(fn=cmd_list)

    sp = sub.add_parser("search", help="case-insensitive substring search")
    sp.add_argument("--text", required=True)
    sp.add_argument(
        "--field", choices=["summary", "description", "all"], default="all"
    )
    sp.set_defaults(fn=cmd_search)

    sp = sub.add_parser("get", help="fetch one event")
    sp.add_argument("--uuid", default=None)
    sp.add_argument("--rowid", type=int, default=None)
    sp.set_defaults(fn=cmd_get)

    sp = sub.add_parser(
        "selftest",
        help="run machine-checkable invariants; exit 1 on any failure",
    )
    sp.set_defaults(fn=cmd_selftest)

    args = p.parse_args()

    try:
        db_path, tmp, con = open_store()
    except (CalendarError, sqlite3.Error, OSError) as e:
        fail(f"{type(e).__name__}: {e}")

    try:
        args.fn(args, con, db_path)
    except (CalendarError, sqlite3.Error, ValueError) as e:
        fail(f"{type(e).__name__}: {e}")
    finally:
        con.close()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
