"""Fixing a camera clock after the event.

A camera clock that was never set, or that reset itself when the battery went
flat, is the commonest fault in a set of photographic records. `entolog check`
finds it. This repairs it, in one pass, without touching the photographs.

Where the camera also recorded a GPS fix, the satellites carry the correct time,
so the error can be measured rather than guessed. The difference between the two
is a whole time zone plus whatever the clock is out by, and those are separated
here so a recorder in British Summer Time is not told their clock is an hour
wrong.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta

HOUR = 3600


def parse_shift(text: str) -> int:
    """'+3h12m', '-45m', '2h', '90' (seconds) to a number of seconds."""
    text = (text or "").strip().lower().replace(" ", "")
    if not text:
        raise ValueError("give a shift, such as +3h12m or -45m")
    sign = -1 if text.startswith("-") else 1
    text = text.lstrip("+-")
    if re.fullmatch(r"\d+", text):
        return sign * int(text)
    total, found = 0, False
    for value, unit in re.findall(r"(\d+)([dhms])", text):
        total += int(value) * {"d": 86400, "h": 3600, "m": 60, "s": 1}[unit]
        found = True
    if not found:
        raise ValueError(f"{text!r} is not a shift. Try +3h12m, -45m or 2h")
    return sign * total


def describe(seconds: int) -> str:
    sign = "-" if seconds < 0 else "+"
    seconds = abs(int(seconds))
    parts = []
    for size, unit in ((86400, "d"), (3600, "h"), (60, "m"), (1, "s")):
        if seconds >= size:
            parts.append(f"{seconds // size}{unit}")
            seconds %= size
    return sign + ("".join(parts) or "0s")


def _when(row):
    try:
        return datetime.fromisoformat((row["taken_at"] or "")[:19])
    except ValueError:
        return None


def against_gps(cx, flt=None) -> dict:
    """Measure the camera clock against the satellites, where both are known."""
    deltas = []
    for row in cx.execute("SELECT id, taken_at, taken_source, exif FROM photos "
                          "WHERE taken_source='exif'"):
        try:
            ex = json.loads(row["exif"] or "{}")
        except json.JSONDecodeError:
            continue
        utc = ex.get("gps_datetime_utc")
        local = _when(row)
        if not utc or local is None:
            continue
        try:
            fix = datetime.strptime(utc, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
        deltas.append((local - fix).total_seconds())
    if not deltas:
        return {"photos": 0}
    deltas.sort()
    median = deltas[len(deltas) // 2]
    # The difference is a time zone plus whatever the clock is out by, and
    # nothing in the file says which is which. Offer both readings rather than
    # picking one and being quietly wrong.
    below = math.floor(median / HOUR) * HOUR
    above = math.ceil(median / HOUR) * HOUR
    return {"photos": len(deltas), "median": median, "spread": deltas[-1] - deltas[0],
            "zones": sorted({below, above}),
            "nearest": round(median / HOUR) * HOUR}


def shift(cx, seconds: int, only_exif=True, gap_seconds=150) -> dict:
    """Move every date by the same amount, and say what was moved. The source
    column records that it happened, so a corrected date is never mistaken for
    one that came straight off the camera."""
    from . import scan
    where = "WHERE taken_source LIKE 'exif%'" if only_exif else ""
    rows = cx.execute(f"SELECT id, taken_at, taken_source FROM photos {where}").fetchall()
    moved = 0
    for row in rows:
        when = _when(row)
        if when is None:
            continue
        new = when + timedelta(seconds=seconds)
        tail = (row["taken_at"] or "")[19:]        # sub seconds and any offset
        source = row["taken_source"]
        source = source if source.endswith("+corrected") else source + "+corrected"
        cx.execute("UPDATE photos SET taken_at=?, taken_source=? WHERE id=?",
                   (new.strftime("%Y-%m-%dT%H:%M:%S") + tail, source, row["id"]))
        moved += 1
    history = json_history(cx)
    history.append({"seconds": seconds, "photos": moved})
    cx.execute("INSERT INTO meta(k,v) VALUES('clock_shifts',?) "
               "ON CONFLICT(k) DO UPDATE SET v=excluded.v", (json.dumps(history),))
    cx.commit()
    groups = scan.regroup(cx, gap_seconds=gap_seconds)
    return {"photos": moved, "seconds": seconds, "groups": groups}


def json_history(cx) -> list:
    row = cx.execute("SELECT v FROM meta WHERE k='clock_shifts'").fetchone()
    try:
        return json.loads(row["v"]) if row else []
    except (json.JSONDecodeError, TypeError):
        return []


def zone_seconds(text: str) -> int:
    """'+1h', '-5h30m', '0' to a time zone in seconds."""
    return parse_shift(text)


def offset_to(cx, photo, when_text: str) -> int:
    """How far out the clock is, given what one photograph should have said."""
    for shape in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M",
                  "%Y-%m-%dT%H:%M"):
        try:
            want = datetime.strptime(when_text.strip(), shape)
            break
        except ValueError:
            continue
    else:
        raise ValueError(f"{when_text!r} is not a date and time. "
                         f"Try '2026-06-14 09:26' or '2026-06-14 09:26:00'")
    has = _when(photo)
    if has is None:
        raise ValueError(f"{photo['filename']} has no date to correct")
    return int((want - has).total_seconds())
