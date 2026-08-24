"""The table, in the shapes a record actually gets used in: a plain spreadsheet,
Darwin Core for GBIF/iRecord, GeoJSON for a map, and JSON for anything else."""

from __future__ import annotations

import csv
import io
import json
import sys

BASIC = ["filename", "date", "time", "latitude", "longitude", "species", "stage", "sex", "comments"]
FULL = BASIC + ["confidence", "altitude_m", "coord_uncertainty_m", "position", "group",
                "date_source", "camera", "lens", "folder", "path"]

DWC = [
    ("occurrenceID", "occurrence_id"), ("basisOfRecord", "basis"),
    ("scientificName", "species"), ("eventDate", "event_date"),
    ("decimalLatitude", "latitude"), ("decimalLongitude", "longitude"),
    ("geodeticDatum", "datum"), ("coordinateUncertaintyInMeters", "coord_uncertainty_m"),
    ("minimumElevationInMeters", "altitude_m"), ("lifeStage", "stage"), ("sex", "sex"),
    ("individualCount", "count"), ("occurrenceRemarks", "comments"),
    ("identificationQualifier", "qualifier"), ("identificationVerificationStatus", "confidence"),
    ("recordedBy", "recorded_by"), ("identifiedBy", "recorded_by"),
    ("associatedMedia", "filename"), ("recordNumber", "record_number"),
]


def rows(cx, only_determined=True, order="taken_at, rel_path"):
    """Flatten photos + records into export dicts."""
    q = ("SELECT p.*, r.species, r.stage, r.sex, r.comments, r.confidence, r.flagged "
         "FROM photos p LEFT JOIN records r ON r.photo_id=p.id")
    if only_determined:
        q += " WHERE COALESCE(r.species,'') != ''"
    q += f" ORDER BY {order}"
    meta_recorder = cx.execute("SELECT v FROM meta WHERE k='recorded_by'").fetchone()
    recorder = json.loads(meta_recorder["v"]) if meta_recorder else ""
    for r in cx.execute(q):
        taken = r["taken_at"] or ""
        date, _, time = taken.partition("T")
        lat, lon = r["lat"], r["lon"]
        conf = (r["confidence"] or "")
        yield {
            "filename": r["filename"],
            "date": date,
            "time": time[:8],
            "latitude": lat, "longitude": lon,
            "position": f"{lat:.6f}, {lon:.6f}" if lat is not None and lon is not None else "",
            "species": r["species"] or "",
            "stage": r["stage"] or "",
            "sex": r["sex"] or "",
            "comments": r["comments"] or "",
            "confidence": conf,
            "qualifier": "?" if conf in ("probable", "aggregate") else "",
            "altitude_m": r["altitude"],
            "coord_uncertainty_m": r["gps_accuracy_m"],
            "group": r["group_id"],
            "date_source": r["taken_source"],
            "camera": r["camera"] or "", "lens": r["lens"] or "",
            "folder": r["rel_path"].rsplit("/", 1)[0] if "/" in r["rel_path"] else "",
            "path": r["path"],
            "event_date": taken,
            "occurrence_id": f"{r['fingerprint']}",
            "record_number": r["id"],
            "basis": "HumanObservation",
            "datum": "WGS84" if lat is not None else "",
            "count": 1,
            "recorded_by": recorder,
        }


def _write_delim(out, data, columns, delim=","):
    w = csv.DictWriter(out, fieldnames=columns, extrasaction="ignore",
                       delimiter=delim, lineterminator="\n")
    w.writeheader()
    for d in data:
        w.writerow({k: ("" if d.get(k) is None else d.get(k)) for k in columns})


def render(cx, fmt="csv", columns=None, only_determined=True) -> str:
    data = list(rows(cx, only_determined=only_determined))
    out = io.StringIO()
    if fmt in ("csv", "tsv"):
        cols = columns or BASIC
        _write_delim(out, data, cols, "\t" if fmt == "tsv" else ",")
    elif fmt == "full":
        _write_delim(out, data, columns or FULL)
    elif fmt == "dwc":
        cols = [t for t, _ in DWC]
        mapped = [{t: d.get(s, "") for t, s in DWC} for d in data]
        _write_delim(out, mapped, cols)
    elif fmt == "json":
        json.dump(data, out, indent=2, default=str)
    elif fmt == "geojson":
        feats = [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [d["longitude"], d["latitude"]]},
            "properties": {k: d[k] for k in
                           ("filename", "date", "time", "species", "stage", "sex", "comments")},
        } for d in data if d["latitude"] is not None]
        json.dump({"type": "FeatureCollection", "features": feats}, out, indent=2, default=str)
    elif fmt == "md":
        cols = columns or BASIC
        out.write("| " + " | ".join(cols) + " |\n")
        out.write("|" + "|".join(["---"] * len(cols)) + "|\n")
        for d in data:
            out.write("| " + " | ".join(str(d.get(c, "") or "").replace("|", "\\|")
                                        for c in cols) + " |\n")
    else:
        raise ValueError(f"unknown format {fmt!r}")
    return out.getvalue()


def summary(cx) -> str:
    total = cx.execute("SELECT COUNT(*) c FROM photos").fetchone()["c"]
    done = cx.execute("SELECT COUNT(*) c FROM records WHERE species!=''").fetchone()["c"]
    spp = cx.execute("SELECT COUNT(DISTINCT species) c FROM records WHERE species!=''").fetchone()["c"]
    gps = cx.execute("SELECT COUNT(*) c FROM photos WHERE lat IS NOT NULL").fetchone()["c"]
    nod = cx.execute("SELECT COUNT(*) c FROM photos WHERE taken_source!='exif'").fetchone()["c"]
    lines = [f"{done}/{total} photos determined, {spp} species",
             f"{gps}/{total} have a position" + (f", {nod} fell back to file date" if nod else "")]
    top = cx.execute("SELECT species, COUNT(*) n FROM records WHERE species!='' "
                     "GROUP BY species ORDER BY n DESC LIMIT 8").fetchall()
    if top:
        lines.append("most recorded: " + ", ".join(f"{r['species']} ({r['n']})" for r in top))
    return "\n".join(lines)
