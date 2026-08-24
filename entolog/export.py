"""The table, in the shapes a record gets used in. Columns come from the active
profile, so a recorder who defined their own fields exports their own fields."""

from __future__ import annotations

import csv
import io
import json

from . import profile as P
from . import records

# Terms that come from the photograph itself, not from the recorder.
DWC_PHOTO = [
    ("occurrenceID", "occurrence_id"), ("basisOfRecord", "basis"),
    ("eventDate", "datetime"), ("decimalLatitude", "latitude"),
    ("decimalLongitude", "longitude"), ("geodeticDatum", "datum"),
    ("coordinateUncertaintyInMeters", "coord_uncertainty_m"),
    ("minimumElevationInMeters", "altitude_m"), ("locality", "locality"),
    ("verbatimCoordinates", "gridref"), ("recordedBy", "recorded_by"),
    ("associatedMedia", "filename"), ("recordNumber", "record_number"),
]


def photo_part(r, recorder="") -> dict:
    taken = r["taken_at"] or ""
    date, _, time = taken.partition("T")
    lat, lon = r["lat"], r["lon"]
    rel = r["rel_path"] or ""
    return {
        "filename": r["filename"], "date": date, "time": time[:8], "datetime": taken,
        "latitude": lat, "longitude": lon,
        "position": f"{lat:.6f}, {lon:.6f}" if lat is not None and lon is not None else "",
        "locality": r["locality"] or "", "gridref": r["gridref"] or "",
        "altitude_m": r["altitude"], "coord_uncertainty_m": r.get("gps_accuracy_m"),
        "group": r["group_id"], "date_source": r["taken_source"],
        "camera": r["camera"] or "", "lens": r["lens"] or "",
        "folder": rel.rsplit("/", 1)[0] if "/" in rel else "",
        "path": r.get("path", ""), "record_number": r["id"],
        "occurrence_id": r.get("fingerprint") or f"entolog:{r['id']}",
        "basis": "HumanObservation", "datum": "WGS84" if lat is not None else "",
        "recorded_by": recorder,
    }


def rows(cx, prof=None, only_determined=True):
    prof = prof or P.active(cx)
    recorder = cx.execute("SELECT v FROM meta WHERE k='recorded_by'").fetchone()
    recorder = json.loads(recorder["v"]) if recorder else ""
    for r in records.list_photos(cx, prof, "done" if only_determined else "all",
                                 limit=10 ** 9):
        d = photo_part(r, recorder)
        for f in prof["fields"]:
            d[f["name"]] = r["values"].get(f["name"], "")
        d["flagged"] = r["flagged"]
        yield d


def _delim(out, data, columns, delim=","):
    w = csv.DictWriter(out, fieldnames=columns, extrasaction="ignore",
                       delimiter=delim, lineterminator="\n")
    w.writeheader()
    for d in data:
        w.writerow({k: ("" if d.get(k) is None else d.get(k)) for k in columns})


def dwc_columns(prof) -> list:
    """(term, source key) pairs: the photograph's terms, then the profile's."""
    cols = list(DWC_PHOTO)
    seen = {t for t, _ in cols}
    for f in prof["fields"]:
        term = f.get("dwc")
        if term and term not in seen:
            cols.append((term, f["name"]))
            seen.add(term)
    if "individualCount" not in seen:
        cols.append(("individualCount", "_one"))
    return cols


def render(cx, fmt="csv", columns=None, only_determined=True, prof=None) -> str:
    prof = prof or P.active(cx)
    data = list(rows(cx, prof, only_determined=only_determined))
    out = io.StringIO()
    if fmt in ("csv", "tsv"):
        _delim(out, data, columns or prof["export"]["columns"],
               "\t" if fmt == "tsv" else ",")
    elif fmt == "full":
        cols = columns or (list(P.PHOTO_FIELDS) + P.names(prof) + ["flagged"])
        _delim(out, data, cols)
    elif fmt == "dwc":
        pairs = dwc_columns(prof)
        mapped = [{t: (1 if s == "_one" else d.get(s, "")) for t, s in pairs} for d in data]
        _delim(out, mapped, [t for t, _ in pairs])
    elif fmt == "json":
        json.dump(data, out, indent=2, default=str)
    elif fmt == "geojson":
        keep = ["filename", "date", "time", "locality"] + P.names(prof)
        feats = [{"type": "Feature",
                  "geometry": {"type": "Point", "coordinates": [d["longitude"], d["latitude"]]},
                  "properties": {k: d.get(k, "") for k in keep}}
                 for d in data if d["latitude"] is not None]
        json.dump({"type": "FeatureCollection", "features": feats}, out, indent=2, default=str)
    elif fmt == "md":
        cols = columns or prof["export"]["columns"]
        out.write("| " + " | ".join(cols) + " |\n")
        out.write("|" + "|".join(["---"] * len(cols)) + "|\n")
        for d in data:
            out.write("| " + " | ".join(str(d.get(c, "") or "").replace("|", "\\|")
                                        for c in cols) + " |\n")
    else:
        raise ValueError(f"unknown format {fmt!r}")
    return out.getvalue()


def summary(cx, prof=None) -> str:
    prof = prof or P.active(cx)
    primary = prof["primary"]
    c = records.counts(cx, prof)
    distinct = cx.execute("SELECT COUNT(DISTINCT value) c FROM field_values "
                          "WHERE field=? AND value!=''", (primary,)).fetchone()["c"]
    gps = cx.execute("SELECT COUNT(*) c FROM photos WHERE lat IS NOT NULL").fetchone()["c"]
    nod = cx.execute("SELECT COUNT(*) c FROM photos WHERE taken_source!='exif'").fetchone()["c"]
    lines = [f"profile {prof['name']}: {', '.join(P.names(prof))}",
             f"{c['done']}/{c['total']} photos have a {primary}, {distinct} distinct",
             f"{gps}/{c['total']} have a position"
             + (f", {nod} fell back to the file date" if nod else "")]
    top = cx.execute("SELECT value, COUNT(*) n FROM field_values WHERE field=? AND value!='' "
                     "GROUP BY value ORDER BY n DESC LIMIT 8", (primary,)).fetchall()
    if top:
        lines.append("most recorded: " + ", ".join(f"{r['value']} ({r['n']})" for r in top))
    return "\n".join(lines)
