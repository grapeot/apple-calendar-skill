"""Read-only query CLI for the macOS Apple Calendar store.

Commands print JSON. Exit codes: 0 success, 1 error, 2 usage.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sqlite3
import sys
from zoneinfo import ZoneInfo

from .store import (
    BASE_COLS,
    BASE_FROM,
    STORE_DIR_ENV,
    CalendarError,
    open_store,
    row_to_event,
    using_default_store,
)
from .timeutil import (
    EPOCH_OFFSET_1970,
    local_date_to_utc_seconds,
    local_tz,
    secs_to_utc,
    wall_iso,
)


def fail(msg: str) -> None:
    print(f"apple_calendar: {msg}", file=sys.stderr)
    sys.exit(1)


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

    if using_default_store():
        add(
            "store_is_group_container",
            "/Group Containers/group.com.apple.calendar/" in db_path,
            db_path,
        )
    else:
        add("store_is_group_container", True,
            f"override store ({STORE_DIR_ENV} set); identity check relaxed")

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


def build_parser() -> argparse.ArgumentParser:
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

    return p


def main(argv: list[str] | None = None) -> None:
    p = build_parser()
    args = p.parse_args(argv)

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

    sys.exit(0)


if __name__ == "__main__":
    main()