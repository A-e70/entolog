"""Folder -> photo rows. Idempotent: re-running picks up new files, notices moved
ones by fingerprint (keeping their determination) and leaves everything else alone."""

from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime
from pathlib import Path

from . import exifread, locality

IMAGE_EXT = {
    ".jpg", ".jpeg", ".jpe", ".png", ".tif", ".tiff", ".webp", ".heic", ".heif",
    ".dng", ".nef", ".nrw", ".cr2", ".cr3", ".crw", ".arw", ".srf", ".sr2",
    ".raf", ".orf", ".rw2", ".pef", ".raw", ".3fr", ".iiq",
}


def fingerprint(path: Path, size: int) -> str:
    """Cheap stable identity: size plus a hash of the head and tail of the file.
    Full hashing a folder of 40 MB raws would dominate the scan for no gain."""
    h = hashlib.sha1(str(size).encode())
    with open(path, "rb") as fh:
        h.update(fh.read(262_144))
        if size > 327_680:
            fh.seek(-65_536, os.SEEK_END)
            h.update(fh.read(65_536))
    return h.hexdigest()[:24]


def place_key(lat: float, lon: float, dp: int = 4) -> str:
    """Positions rounded to about 10 m. One lookup then covers a whole burst."""
    return f"{lat:.{dp}f},{lon:.{dp}f}"


def haversine_m(a_lat, a_lon, b_lat, b_lon) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp = p2 - p1
    dl = math.radians(b_lon - a_lon)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(x)))


def _sort_key(row) -> tuple:
    return (row["taken_at"] or "9999", row["rel_path"].lower())


def regroup(cx, gap_seconds: int = 150, move_metres: float = 60.0) -> int:
    """Cluster photos into specimen events: consecutive shots close in time and
    place are almost always the same individual, so they can be determined once."""
    rows = cx.execute("SELECT id, taken_at, lat, lon, rel_path FROM photos").fetchall()
    rows = sorted(rows, key=_sort_key)
    gid, prev = 0, None
    for seq, row in enumerate(rows):
        new = prev is None
        if prev is not None:
            t1, t2 = prev["taken_at"], row["taken_at"]
            if t1 and t2:
                try:
                    dt = abs((datetime.fromisoformat(t2) - datetime.fromisoformat(t1)).total_seconds())
                    new = dt > gap_seconds
                except ValueError:
                    new = True
            else:
                new = Path(prev["rel_path"]).parent != Path(row["rel_path"]).parent
            if not new and None not in (prev["lat"], prev["lon"], row["lat"], row["lon"]):
                if haversine_m(prev["lat"], prev["lon"], row["lat"], row["lon"]) > move_metres:
                    new = True
        if new:
            gid += 1
        cx.execute("UPDATE photos SET group_id=?, seq=? WHERE id=?", (gid, seq, row["id"]))
        prev = row
    cx.commit()
    return gid


def scan(cx, roots, recursive=True, gap_seconds=150, progress=None) -> dict:
    added = updated = moved = skipped = 0
    seen_paths = set()
    for root in roots:
        root = Path(root).expanduser().resolve()
        if root.is_file():
            files = [root]
        else:
            files = sorted(root.rglob("*") if recursive else root.glob("*"))
        for f in files:
            if not f.is_file() or f.suffix.lower() not in IMAGE_EXT or f.name.startswith("."):
                continue
            p = str(f)
            seen_paths.add(p)
            st = f.stat()
            existing = cx.execute("SELECT id, bytes FROM photos WHERE path=?", (p,)).fetchone()
            if existing and existing["bytes"] == st.st_size:
                skipped += 1
                continue
            fp = fingerprint(f, st.st_size)
            ex = exifread.read(f)
            taken = ex.get("datetime_original")
            source = "exif"
            if not taken:  # no EXIF date: file mtime, marked as such so it is auditable
                taken = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%dT%H:%M:%S")
                source = "file-mtime"
            rel = str(f.relative_to(root)) if root.is_dir() else f.name
            vals = dict(
                path=p, filename=f.name, rel_path=rel, fingerprint=fp, bytes=st.st_size,
                taken_at=taken, taken_source=source, lat=ex.get("lat"), lon=ex.get("lon"),
                altitude=ex.get("altitude"), gps_accuracy_m=ex.get("gps_accuracy_m"),
                orientation=ex.get("orientation", 1), camera=ex.get("camera"),
                lens=ex.get("lens"), width=ex.get("width"), height=ex.get("height"),
                thumb_offset=ex.get("thumb_offset"), thumb_length=ex.get("thumb_length"),
                exif=json.dumps(ex, default=str),
                gridref=(locality.osgb_gridref(ex["lat"], ex["lon"])
                         if ex.get("lat") is not None else None),
            )
            cols = ",".join(vals)
            cx.execute(
                f"INSERT INTO photos({cols}) VALUES({','.join('?' * len(vals))}) "
                f"ON CONFLICT(path) DO UPDATE SET {','.join(f'{c}=excluded.{c}' for c in vals)}",
                tuple(vals.values()))
            pid = cx.execute("SELECT id FROM photos WHERE path=?", (p,)).fetchone()["id"]
            # A file that moved or was renamed keeps the record typed against it,
            # whatever fields that record happens to have.
            donor = cx.execute(
                "SELECT fv.field, fv.value FROM field_values fv "
                "JOIN photos ph ON ph.id=fv.photo_id "
                "WHERE ph.fingerprint=? AND ph.id!=? AND fv.value!=''", (fp, pid)).fetchall()
            if donor:
                for d in donor:
                    cx.execute(
                        "INSERT INTO field_values(photo_id, field, value, updated_at) "
                        "VALUES(?,?,?,datetime('now')) "
                        "ON CONFLICT(photo_id, field) DO NOTHING",
                        (pid, d["field"], d["value"]))
                moved += 1
            if ex.get("lat") is not None:
                place = cx.execute("SELECT verbose, short FROM places WHERE key=?",
                                   (place_key(ex["lat"], ex["lon"]),)).fetchone()
                if place:
                    cx.execute("UPDATE photos SET locality=?, locality_full=? WHERE id=?",
                               (place["short"], place["verbose"], pid))
            if existing:
                updated += 1
            else:
                added += 1
            if progress and (added + updated) % 25 == 0:
                progress(added + updated, f.name)
    cx.commit()
    missing = 0
    for row in cx.execute("SELECT id, path FROM photos").fetchall():
        if not Path(row["path"]).exists():
            missing += 1
    groups = regroup(cx, gap_seconds=gap_seconds)
    return {"added": added, "updated": updated, "recovered": moved,
            "unchanged": skipped, "missing": missing, "groups": groups}
