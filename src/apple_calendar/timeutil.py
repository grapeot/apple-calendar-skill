"""Reference-date and clock conversion for the Apple Calendar EventKit store.

The store keeps `start_date` / `end_date` as ABSOLUTE seconds since
2001-01-01T00:00:00Z (the NSDate reference). These helpers convert those
values to UTC instants and to wall-clock strings in an event's original
timezone. They exist so the rest of the code never re-derives the semantics.
"""
from __future__ import annotations

import datetime as dt
import os
import sys
from zoneinfo import ZoneInfo

REF_UTC = dt.datetime(2001, 1, 1, tzinfo=dt.timezone.utc)

# 2001-01-01T00:00:00Z expressed in 1970-unix seconds; used to hand sqlite a
# real unix timestamp for date()/strftime() on stored reference-date values.
EPOCH_OFFSET_1970 = 978307200

FLOAT_TZ_NAMES = ("_float", "float")


def secs_to_utc(ts) -> dt.datetime | None:
    if ts is None:
        return None
    return REF_UTC + dt.timedelta(seconds=float(ts))


def utc_iso(ts) -> str | None:
    d = secs_to_utc(ts)
    return d.strftime("%Y-%m-%dT%H:%M:%SZ") if d is not None else None


def wall_iso(ts, tz_name) -> str | None:
    d = secs_to_utc(ts)
    if d is None or not tz_name or tz_name in FLOAT_TZ_NAMES:
        return None
    try:
        zi = ZoneInfo(tz_name)
    except Exception:
        return None
    return d.astimezone(zi).isoformat()


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
    """A local calendar date's midnight (or 23:59:59) as an absolute instant,
    in the store's reference-date seconds."""
    d = dt.date.fromisoformat(date_str)
    tz = local_tz()
    hh, mm, ss = (23, 59, 59) if end_of_day else (0, 0, 0)
    wall = dt.datetime(d.year, d.month, d.day, hh, mm, ss, tzinfo=tz)
    return (wall - REF_UTC).total_seconds()