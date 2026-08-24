"""The table, in the shapes a record gets used in. Columns come from the active
profile, so a recorder who defined their own fields exports their own fields."""

from __future__ import annotations

import csv
import io
import json
import uuid
import zipfile
from datetime import datetime, timezone

from . import locality
from . import profile as P
from . import taxonomy
from . import records

# GBIF will not register a dataset unless the licence is one of these three.
LICENCES = {
    "CC0": ("CC0 1.0", "http://creativecommons.org/publicdomain/zero/1.0/legalcode"),
    "CC-BY": ("CC BY 4.0", "http://creativecommons.org/licenses/by/4.0/legalcode"),
    "CC-BY-NC": ("CC BY-NC 4.0", "http://creativecommons.org/licenses/by-nc/4.0/legalcode"),
}

# Terms that come from the photograph itself, not from the recorder.
DWC_PHOTO = [
    ("occurrenceID", "occurrence_id"), ("basisOfRecord", "basis"),
    ("eventDate", "datetime"), ("decimalLatitude", "latitude"),
    ("decimalLongitude", "longitude"), ("geodeticDatum", "datum"),
    ("coordinateUncertaintyInMeters", "coord_uncertainty_m"),
    ("minimumElevationInMeters", "altitude_m"), ("locality", "locality"),
    ("verbatimCoordinates", "gridref"), ("recordedBy", "recorded_by"),
    ("associatedMedia", "filename"), ("recordNumber", "record_number"),
    ("occurrenceStatus", "status"), ("informationWithheld", "information_withheld"),
    ("verbatimCoordinateSystem", "grid_system"),
]

# Only written when the recorder has loaded a taxon list.
DWC_TAXON = [("taxonID", "taxon_id"), ("scientificNameAuthorship", "authority"),
             ("taxonRank", "taxon_rank"), ("acceptedNameUsage", "accepted_name")]

# iRecord takes any headings and asks you to map them, but these are the labels
# it offers, so a file using them maps itself.
IRECORD = [
    ("Species or taxon name", None), ("Date", "date_uk"),
    ("Spatial reference", "spatial_ref"), ("Location name", "locality"),
    ("Recorder Name", "recorded_by"), ("Identified By", "recorded_by"),
    ("Quantity", None), ("Stage", None), ("Sex", None),
    ("Occurrence comment", None), ("Recorder certainty", None),
    ("Sensitivity precision", "sensitivity"), ("Taxon Version Key", "taxon_id"),
]


def photo_part(r, recorder="", precision="") -> dict:
    """One photograph's own columns. A record marked sensitive, or a whole
    dataset told to be coarse, is published as the grid square it falls in and
    the middle of that square, never as the position in the file."""
    taken = r["taken_at"] or ""
    date, _, time = taken.partition("T")
    lat, lon = r["lat"], r["lon"]
    rel = r["rel_path"] or ""
    ref, withheld, uncertainty = r["gridref"] or "", "", r.get("gps_accuracy_m")
    if precision and lat is not None:
        lat, lon, ref, uncertainty = locality.blur_position(
            lat, lon, precision, r["gridref_system"] or "auto")
        withheld = f"coordinates given as the {precision} square they fall in"
    elif precision and ref:
        ref = locality.blur(ref, precision)
        withheld = f"grid reference given to {precision}"
    return {
        "filename": r["filename"], "date": date, "time": time[:8], "datetime": taken,
        "latitude": lat, "longitude": lon,
        "position": f"{lat:.6f}, {lon:.6f}" if lat is not None and lon is not None else "",
        "locality": r["locality"] or "", "gridref": ref,
        "grid_system": r["gridref_system"] or "",
        "altitude_m": r["altitude"], "coord_uncertainty_m": uncertainty,
        "precision": precision or "exact", "information_withheld": withheld,
        "group": r["group_id"], "date_source": r["taken_source"],
        "camera": r["camera"] or "", "lens": r["lens"] or "",
        "folder": rel.rsplit("/", 1)[0] if "/" in rel else "",
        "path": r.get("path", ""), "record_number": r["id"],
        "record_on_photograph": 1,
        "occurrence_id": r.get("fingerprint") or f"entolog:{r['id']}",
        "basis": "HumanObservation", "datum": "WGS84" if lat is not None else "",
        "recorded_by": recorder, "status": "present",
        "date_uk": f"{date[8:10]}/{date[5:7]}/{date[0:4]}" if len(date) == 10 else "",
        "spatial_ref": ref or (f"{lat:.5f}, {lon:.5f}" if lat is not None else ""),
        "sensitivity": (locality.PRECISION_METRES.get(precision, "")
                        if precision else ""),
    }


def setting(cx, key, default=""):
    row = cx.execute("SELECT v FROM meta WHERE k=?", (key,)).fetchone()
    return json.loads(row["v"]) if row else default


def dataset_id(cx) -> str:
    """A stable id for this set of records, so an occurrenceID is unique in the
    world and not just on this laptop."""
    got = setting(cx, "dataset_id", "")
    if not got:
        got = str(uuid.uuid4())
        cx.execute("INSERT INTO meta(k,v) VALUES('dataset_id',?) "
                   "ON CONFLICT(k) DO UPDATE SET v=excluded.v", (json.dumps(got),))
        cx.commit()
    return got


def rows(cx, prof=None, only_determined=True):
    prof = prof or P.active(cx)
    recorder = setting(cx, "recorded_by", "")
    default_blur = setting(cx, "blur", "")
    dsid = dataset_id(cx)
    primary, taxon_cache = prof["primary"], {}
    for r in records.list_photos(cx, prof, "done" if only_determined else "all",
                                 limit=10 ** 9):
      for occ, vals, flagged, precision in records.each_record(r):
        if only_determined and not vals.get(primary):
            continue
        d = photo_part(r, recorder, precision or default_blur)
        # The first record on a photograph keeps the identifier it always had.
        d["occurrence_id"] = (f"urn:entolog:{dsid}:{r['fingerprint']}"
                              + ("" if occ == 1 else f":{occ}"))
        d["record_number"] = r["id"] if occ == 1 else f"{r['id']}.{occ}"
        d["record_on_photograph"] = occ
        for f in prof["fields"]:
            d[f["name"]] = vals.get(f["name"], "")
        d["flagged"] = flagged
        name = vals.get(primary, "")
        if name:
            if name not in taxon_cache:
                taxon_cache[name] = taxonomy.lookup(cx, name) or {}
            t = taxon_cache[name]
            d["taxon_id"] = t.get("taxon_id", "")
            d["authority"] = t.get("authority", "")
            d["taxon_rank"] = t.get("rank", "")
            d["accepted_name"] = t.get("accepted", "")
        yield d


def _delim(out, data, columns, delim=","):
    w = csv.DictWriter(out, fieldnames=columns, extrasaction="ignore",
                       delimiter=delim, lineterminator="\n")
    w.writeheader()
    for d in data:
        w.writerow({k: ("" if d.get(k) is None else d.get(k)) for k in columns})


def dwc_columns(prof, with_taxa=False) -> list:
    """(term, source key) pairs: the photograph's terms, then the profile's."""
    cols = list(DWC_PHOTO) + (list(DWC_TAXON) if with_taxa else [])
    seen = {t for t, _ in cols}
    for f in prof["fields"]:
        term = f.get("dwc")
        if term and term not in seen:
            cols.append((term, f["name"]))
            seen.add(term)
    if "individualCount" not in seen:
        cols.append(("individualCount", "_one"))
    return cols


def _irecord_map(prof) -> dict:
    """Match profile fields to iRecord's columns by their Darwin Core term,
    which is the only thing the two have in common."""
    by_term = {f.get("dwc"): f["name"] for f in prof["fields"] if f.get("dwc")}
    return {
        "Species or taxon name": by_term.get("scientificName", prof["primary"]),
        "Quantity": by_term.get("individualCount"),
        "Stage": by_term.get("lifeStage"),
        "Sex": by_term.get("sex"),
        "Occurrence comment": by_term.get("occurrenceRemarks"),
        "Recorder certainty": by_term.get("identificationVerificationStatus"),
    }


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
        pairs = dwc_columns(prof, with_taxa=taxonomy.count(cx) > 0)
        mapped = [{t: (1 if s == "_one" else d.get(s, "")) for t, s in pairs} for d in data]
        _delim(out, mapped, [t for t, _ in pairs])
    elif fmt == "irecord":
        mapped_from = _irecord_map(prof)
        cols = [c for c, _ in IRECORD]
        out_rows = []
        for d in data:
            row = {}
            for col, source in IRECORD:
                key = source or mapped_from.get(col)
                row[col] = d.get(key, "") if key else ""
            out_rows.append(row)
        _delim(out, out_rows, cols)
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


EML = """<?xml version="1.0" encoding="UTF-8"?>
<eml:eml xmlns:eml="eml://ecoinformatics.org/eml-2.1.1"
         xmlns:dc="http://purl.org/dc/terms/"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="eml://ecoinformatics.org/eml-2.1.1 eml.xsd"
         packageId="{dsid}" system="entolog" scope="system" xml:lang="eng">
  <dataset>
    <alternateIdentifier>{dsid}</alternateIdentifier>
    <title xml:lang="eng">{title}</title>
    <creator>
      <individualName><surName>{creator}</surName></individualName>
      {email}
    </creator>
    <pubDate>{pubdate}</pubDate>
    <language>eng</language>
    <abstract><para>{abstract}</para></abstract>
    <intellectualRights><para>This work is licensed under a
      <ulink url="{licence_url}"><citetitle>{licence}</citetitle></ulink>
      licence.</para></intellectualRights>
    <contact>
      <individualName><surName>{creator}</surName></individualName>
      {email}
    </contact>
  </dataset>
</eml:eml>
"""

META_XML = """<?xml version="1.0" encoding="UTF-8"?>
<archive xmlns="http://rs.tdwg.org/dwc/text/">
  <core rowType="http://rs.tdwg.org/dwc/terms/Occurrence"
        fieldsTerminatedBy="," linesTerminatedBy="\\n" fieldsEnclosedBy="&quot;"
        ignoreHeaderLines="1" encoding="UTF-8">
    <files><location>occurrence.csv</location></files>
    <id index="0" />
{fields}
  </core>
</archive>
"""


def _xml_escape(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def dwca(cx, prof=None, only_determined=True) -> bytes:
    """A Darwin Core Archive: the occurrence table, a descriptor saying what each
    column means, and the dataset metadata. This is what GBIF and the atlases
    take, and it is a zip so it goes in one piece."""
    prof = prof or P.active(cx)
    dsid = dataset_id(cx)
    pairs = dwc_columns(prof, with_taxa=taxonomy.count(cx) > 0)
    body = render(cx, "dwc", only_determined=only_determined, prof=prof)
    fields = "\n".join(
        f'    <field index="{i}" term="http://rs.tdwg.org/dwc/terms/{term}" />'
        for i, (term, _src) in enumerate(pairs))
    licence_key = setting(cx, "licence", "CC-BY")
    licence, licence_url = LICENCES.get(licence_key, LICENCES["CC-BY"])
    creator = setting(cx, "recorded_by", "") or "unnamed recorder"
    email = setting(cx, "contact_email", "")
    eml = EML.format(
        dsid=_xml_escape(dsid),
        title=_xml_escape(setting(cx, "dataset_title", "") or f"entolog records, {prof['title']}"),
        creator=_xml_escape(creator),
        email=f"<electronicMailAddress>{_xml_escape(email)}</electronicMailAddress>" if email else "",
        pubdate=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        abstract=_xml_escape(setting(cx, "abstract", "") or
                             "Species records made from photographs with entolog."),
        licence=_xml_escape(licence), licence_url=_xml_escape(licence_url))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("occurrence.csv", body)
        z.writestr("meta.xml", META_XML.format(fields=fields))
        z.writestr("eml.xml", eml)
    return buf.getvalue()


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
