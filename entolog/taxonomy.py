"""A taxon list, supplied by the recorder, used to check names and to carry an
identifier with every record.

entolog ships no taxonomy. The UK Species Inventory, a GBIF backbone extract and
a scheme's own checklist all have their own terms of use, so the recorder brings
the one they are entitled to and entolog reads whatever columns it has.

What this buys: a name spelled the way the list spells it, a taxon identifier
travelling into the exports, and a warning when a record is filed under a name
the list calls a synonym of something else.
"""

from __future__ import annotations

import csv
import io
import re

# Header names seen in the wild, in the order they are preferred.
COLUMNS = {
    "name": ("scientific name", "scientificname", "taxon name", "taxonname",
             "recommended name", "recommended_name", "preferred name", "taxon",
             "name", "species"),
    "authority": ("scientificnameauthorship", "authority", "author", "attribute"),
    "rank": ("taxonrank", "rank", "taxon rank"),
    "taxon_id": ("taxon version key", "taxonversionkey", "tvk", "taxonid",
                 "taxon_id", "scientificnameid", "recommended_taxon_version_key",
                 "recommended taxon version key", "key", "id"),
    "accepted": ("acceptednameusage", "accepted name", "accepted", "acceptedname",
                 "recommended", "preferred", "valid name"),
    "vernacular": ("vernacularname", "common name", "commonname", "vernacular",
                   "english name", "englishname"),
    "taxon_group": ("taxon group", "taxongroup", "informal group", "group",
                    "organism group"),
}


def _norm(h: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", (h or "").lower()).strip()


def map_columns(header, override=None) -> dict:
    """Which column of this file holds which thing."""
    normed = [_norm(h) for h in header]
    out = {}
    for want, names in COLUMNS.items():
        for candidate in names:
            if candidate in normed:
                out[want] = normed.index(candidate)
                break
    for pair in (override or "").split(","):
        if "=" not in pair:
            continue
        key, _, col = pair.partition("=")
        key, col = key.strip(), _norm(col)
        if key in COLUMNS and col in normed:
            out[key] = normed.index(col)
    return out


def sniff(text: str) -> str:
    first = text.splitlines()[0] if text else ""
    return "\t" if first.count("\t") > first.count(",") else ","


def load(cx, text: str, override=None, replace=True) -> dict:
    """Read a taxon list. Returns what was understood, so the recorder can see
    that the columns were matched to the right things before trusting it."""
    delim = sniff(text)
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    try:
        header = next(reader)
    except StopIteration:
        return {"names": 0, "problem": "the file is empty"}
    at = map_columns(header, override)
    if "name" not in at:
        return {"names": 0, "columns": at,
                "problem": "no column holds the scientific name. Name it, or pass "
                           "--map name=<column>"}
    if replace:
        cx.execute("DELETE FROM taxa")
    n = skipped = 0
    seen = set()
    for row in reader:
        if not row or at["name"] >= len(row):
            continue
        name = row[at["name"]].strip()
        if not name or name.lower() in seen:
            skipped += 1
            continue
        seen.add(name.lower())

        def cell(key):
            i = at.get(key)
            return row[i].strip() if i is not None and i < len(row) else ""

        accepted = cell("accepted")
        cx.execute(
            "INSERT INTO taxa(name, authority, rank, taxon_id, accepted, vernacular, "
            "taxon_group) VALUES(?,?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET "
            "authority=excluded.authority, rank=excluded.rank, "
            "taxon_id=excluded.taxon_id, accepted=excluded.accepted, "
            "vernacular=excluded.vernacular, taxon_group=excluded.taxon_group",
            (name, cell("authority"), cell("rank"), cell("taxon_id"),
             "" if accepted.lower() == name.lower() else accepted,
             cell("vernacular"), cell("taxon_group")))
        n += 1
    cx.commit()
    return {"names": n, "skipped": skipped,
            "columns": {k: header[i] for k, i in at.items()},
            "synonyms": cx.execute("SELECT COUNT(*) c FROM taxa WHERE accepted!=''")
                          .fetchone()["c"]}


def count(cx) -> int:
    return cx.execute("SELECT COUNT(*) c FROM taxa").fetchone()["c"]


def lookup(cx, name: str):
    """The taxon list's entry for a name, matched without regard to case."""
    if not name:
        return None
    row = cx.execute("SELECT * FROM taxa WHERE name=? COLLATE NOCASE",
                     (name.strip(),)).fetchone()
    return dict(row) if row else None


def accepted_for(cx, name: str):
    """(accepted name, its entry) when the list calls this a synonym."""
    got = lookup(cx, name)
    if not got or not got["accepted"]:
        return None, got
    return got["accepted"], (lookup(cx, got["accepted"]) or got)


def as_values(cx) -> dict:
    """The list in the shape the suggestion engine wants."""
    out = {}
    for row in cx.execute("SELECT name, vernacular, accepted, authority, rank, "
                          "taxon_id FROM taxa"):
        note = row["vernacular"] or ""
        if row["accepted"]:
            note = (note + " " if note else "") + f"synonym of {row['accepted']}"
        elif row["authority"]:
            note = note or row["authority"]
        out[row["name"]] = {"value": row["name"], "n": 0, "note": note,
                            "listed": True, "taxon_id": row["taxon_id"] or "",
                            "accepted": row["accepted"] or ""}
    return out
