"""Reading and writing the recorder's own fields.

Everything here is driven by the active profile, so nothing below knows or cares
what the fields are called. `_flag` is entolog's own, kept apart from the
recorder's fields by the leading underscore that profiles are not allowed to use.
"""

from __future__ import annotations

import re

from . import profile as P

FLAG = "_flag"
PRECISION = "_precision"          # how coarsely this record may be published
BUILT_IN = (FLAG, PRECISION)


def values(cx, photo_id: int, occ: int = 1) -> dict:
    return {r["field"]: r["value"] for r in cx.execute(
        "SELECT field, value FROM field_values WHERE photo_id=? AND occ=?",
        (photo_id, occ))}


def occurrences(cx, photo_id: int) -> list:
    """Which records this photograph holds. The first always exists."""
    got = {r["occ"] for r in cx.execute(
        "SELECT DISTINCT occ FROM field_values WHERE photo_id=?", (photo_id,))}
    return sorted(got | {1})          # the first is always there, even when empty


def add_record(cx, photo_id: int, prof=None) -> int:
    """The number a second thing in the same photograph would have: another moth
    in the egg box, another mine on the same leaf.

    Nothing is written. The record exists once something is typed into it, so
    changing your mind leaves nothing behind."""
    row = cx.execute("SELECT COALESCE(MAX(occ), 1) + 1 n FROM field_values "
                     "WHERE photo_id=?", (photo_id,)).fetchone()
    return row["n"]


def remove_record(cx, photo_id: int, occ: int) -> bool:
    """Take a record off a photograph. The first is emptied rather than removed,
    because every photograph has one."""
    if occ <= 1:
        cx.execute("DELETE FROM field_values WHERE photo_id=? AND occ=1", (photo_id,))
        cx.commit()
        return False
    cx.execute("DELETE FROM field_values WHERE photo_id=? AND occ=?", (photo_id, occ))
    cx.commit()
    return True


def _attach(cx, rows):
    """One query for every value on the page, rather than one per photograph."""
    by_id = {r["id"]: r for r in rows}
    for r in rows:
        r["values"] = {}
        r["flagged"] = 0
        r["precision"] = ""
        r["extra"] = {}          # every record after the first, by its number
    if by_id:
        marks = ",".join("?" * len(by_id))
        for v in cx.execute(
                f"SELECT photo_id, occ, field, value FROM field_values "
                f"WHERE photo_id IN ({marks}) ORDER BY occ", tuple(by_id)):
            row = by_id[v["photo_id"]]
            if v["occ"] == 1:
                target = row
            else:
                target = row["extra"].setdefault(
                    str(v["occ"]), {"values": {}, "flagged": 0, "precision": ""})
            if v["field"] == FLAG:
                target["flagged"] = 1 if v["value"] == "1" else 0
            elif v["field"] == PRECISION:
                target["precision"] = v["value"]
            else:
                target["values"][v["field"]] = v["value"]
    for r in rows:
        r["occs"] = 1 + len(r["extra"])
    return rows


def each_record(row):
    """Every record on a listed photograph: (number, values, flagged, precision).
    A photograph almost always has one, and this reads the same either way."""
    yield 1, row["values"], row["flagged"], row["precision"]
    for occ in sorted(row.get("extra", {}), key=int):
        e = row["extra"][occ]
        yield int(occ), e["values"], e["flagged"], e["precision"]


PHOTO_COLS = ("id, filename, rel_path, taken_at, taken_source, lat, lon, altitude, "
              "gridref, locality, orientation, camera, lens, width, height, group_id, "
              "seq, bytes, thumb_offset, path, fingerprint, gridref_system")


def list_photos(cx, prof, flt="all", q="", limit=5000) -> list:
    primary = prof["primary"]
    sql = [f"SELECT {','.join('p.' + c.strip() for c in PHOTO_COLS.split(','))} FROM photos p"]
    args = []
    where = []
    # A photograph counts as recorded when any record on it has a name.
    recorded = ("EXISTS(SELECT 1 FROM field_values f WHERE f.photo_id=p.id "
                "AND f.field=? AND f.value!='')")
    if flt == "todo":
        where.append("NOT " + recorded)
        args.append(primary)
    elif flt == "done":
        where.append(recorded)
        args.append(primary)
    elif flt == "flagged":
        where.append("EXISTS(SELECT 1 FROM field_values f WHERE f.photo_id=p.id "
                     "AND f.field='_flag' AND f.value='1')")
    elif flt == "nogps":
        where.append("p.lat IS NULL")
    if q:
        where.append("(p.filename LIKE ? OR EXISTS(SELECT 1 FROM field_values f "
                     "WHERE f.photo_id=p.id AND f.value LIKE ?))")
        args += [f"%{q}%", f"%{q}%"]
    if where:
        sql.append("WHERE " + " AND ".join(where))
    sql.append(f"ORDER BY p.seq LIMIT {int(limit)}")
    rows = [dict(r) for r in cx.execute(" ".join(sql), args)]
    return _attach(cx, rows)


def counts(cx, prof) -> dict:
    total = cx.execute("SELECT COUNT(*) c FROM photos").fetchone()["c"]
    done = cx.execute("SELECT COUNT(DISTINCT photo_id) c FROM field_values "
                      "WHERE field=? AND value!=''", (prof["primary"],)).fetchone()["c"]
    made = cx.execute("SELECT COUNT(*) c FROM field_values WHERE field=? AND value!=''",
                      (prof["primary"],)).fetchone()["c"]
    return {"total": total, "done": done, "records": made}


KEEP_EDITS = 500          # how far back undo can reach


def next_batch(cx) -> int:
    row = cx.execute("SELECT COALESCE(MAX(batch), 0) + 1 b FROM edits").fetchone()
    return row["b"]


def undo(cx, times: int = 1) -> list:
    """Put back the last change, or the last few. Returns what was put back."""
    done = []
    for _ in range(max(1, times)):
        row = cx.execute("SELECT MAX(batch) b FROM edits").fetchone()
        if row["b"] is None:
            break
        batch = row["b"]
        rows = cx.execute("SELECT * FROM edits WHERE batch=?", (batch,)).fetchall()
        for e in rows:
            cx.execute("INSERT INTO field_values(photo_id, occ, field, value, updated_at) "
                       "VALUES(?,?,?,?,datetime('now')) "
                       "ON CONFLICT(photo_id, occ, field) "
                       "DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                       (e["photo_id"], e["occ"], e["field"], e["was"]))
        cx.execute("DELETE FROM edits WHERE batch=?", (batch,))
        cx.commit()
        done.append({"batch": batch, "values": len(rows),
                     "photos": len({e["photo_id"] for e in rows}),
                     "what": rows[0]["what"] if rows else ""})
    return done


def pending_undo(cx):
    """What the next undo would put back, without doing it."""
    row = cx.execute("SELECT MAX(batch) b FROM edits").fetchone()
    if row["b"] is None:
        return None
    rows = cx.execute("SELECT * FROM edits WHERE batch=?", (row["b"],)).fetchall()
    return {"batch": row["b"], "values": len(rows),
            "photos": len({e["photo_id"] for e in rows}),
            "what": rows[0]["what"] if rows else ""}


def save(cx, prof, photo_id: int, fields: dict, apply_group=False, batch=None,
         occ: int = 1) -> tuple:
    """Write one or more field values. Returns (photo ids touched, {field: error}).
    A value that fails its own rule is still stored: losing what someone typed is
    worse than storing something odd, and the window shows the complaint."""
    known = set(P.names(prof)) | set(BUILT_IN)
    errors, clean = {}, {}
    for k, v in fields.items():
        if k not in known:
            errors[k] = f"there is no field called {k!r} in the {prof['name']} profile"
            continue
        if k == FLAG:
            clean[k] = "1" if str(v) in ("1", "True", "true", "yes") else ""
            continue
        if k == PRECISION:
            from . import locality
            want = str(v or "").strip()
            if want and want not in locality.PRECISION_METRES:
                errors[k] = ("precision must be one of "
                             + ", ".join(locality.PRECISION_METRES))
                continue
            clean[k] = want
            continue
        value, err = P.clean(prof, k, v)
        clean[k] = value
        if err:
            errors[k] = err
    if not clean:
        return [], errors

    targets = [photo_id]
    if apply_group:
        g = cx.execute("SELECT group_id FROM photos WHERE id=?", (photo_id,)).fetchone()
        if g and g["group_id"] is not None:
            targets = [r["id"] for r in cx.execute(
                "SELECT id FROM photos WHERE group_id=? ORDER BY seq", (g["group_id"],))]
    if batch is None:
        batch = next_batch(cx)
    what = ", ".join(f"{k} {v!r}" if v else f"{k} cleared" for k, v in clean.items())
    for t in targets:
        before = values(cx, t, occ)
        for k, v in clean.items():
            was = before.get(k, "")
            if was != v:
                cx.execute(
                    "INSERT INTO edits(batch, photo_id, occ, field, was, became, what, at) "
                    "VALUES(?,?,?,?,?,?,?,datetime('now'))",
                    (batch, t, occ, k, was, v, what))
            cx.execute(
                "INSERT INTO field_values(photo_id, occ, field, value, updated_at) "
                "VALUES(?,?,?,?,datetime('now')) ON CONFLICT(photo_id, occ, field) "
                "DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (t, occ, k, v))
    cx.execute("DELETE FROM edits WHERE batch <= ?", (batch - KEEP_EDITS,))
    for k, v in clean.items():
        f = P.field(prof, k)
        if v and f and (f["learn"] or f["type"] == "choice"):
            learn(cx, k, v)
    cx.commit()
    return targets, errors


def learn(cx, field: str, value: str, uses: int = 1):
    cx.execute("INSERT INTO terms(field, value, uses) VALUES(?,?,?) "
               "ON CONFLICT(field, value) DO UPDATE SET uses=uses+?",
               (field, value, uses, uses))


def known_values(cx, field: str, taxa: bool = False) -> dict:
    """Every value this field holds, with how many records hold it, merged with
    whatever checklist has been loaded. Derived from the records themselves, so
    it needs no upkeep: record a species and it is offered from then on, remove
    the last record of it and it stops being offered."""
    from . import taxonomy
    out = taxonomy.as_values(cx) if taxa else {}
    for row in cx.execute("SELECT value, COUNT(*) n FROM field_values "
                          "WHERE field=? AND value!='' GROUP BY value", (field,)):
        got = out.setdefault(row["value"], {"value": row["value"], "n": 0,
                                            "note": "", "listed": False})
        got["n"] = row["n"]
    for row in cx.execute("SELECT value, note, from_list FROM terms WHERE field=?",
                          (field,)):
        got = out.setdefault(row["value"], {"value": row["value"], "n": 0,
                                            "note": "", "listed": False})
        got["note"] = got["note"] or (row["note"] or "")
        got["listed"] = got["listed"] or bool(row["from_list"])
    return out


# How well a candidate answers what has been typed. Lower is better, None means
# it does not answer it at all.
EXACT, STARTS, WORD, NOTE_STARTS, INITIALS, CONTAINS, NOTE_CONTAINS = range(7)


def _words(s: str):
    return [w for w in re.split(r"[^A-Za-z0-9]+", s) if w]


def _initials_match(value: str, abbrev: str) -> bool:
    """vecr matches Vespa crabro, and nothing else does."""
    words = [w.lower() for w in _words(value)]
    if len(words) < 2 or not abbrev:
        return False
    for cut in range(1, len(abbrev)):
        if words[0].startswith(abbrev[:cut]) and words[1].startswith(abbrev[cut:]):
            return True
    return False


def match_rank(value: str, note: str, q: str):
    v, n, q = value.lower(), (note or "").lower(), q.lower()
    if not q:
        return EXACT
    if v == q:
        return EXACT
    if v.startswith(q):
        return STARTS
    if any(w.lower().startswith(q) for w in _words(value)[1:]):
        return WORD
    if n.startswith(q) or any(w.lower().startswith(q) for w in _words(note)[1:]):
        return NOTE_STARTS
    if " " not in q and len(q) <= 8 and _initials_match(value, q):
        return INITIALS
    if q in v:
        return CONTAINS
    if q in n:
        return NOTE_CONTAINS
    return None


def suggest(cx, field: str, q: str = "", limit: int = 20, taxa: bool = False) -> list:
    """What to offer for a half typed value. Ranked by how well it answers what
    was typed, then by how often it has been recorded here."""
    q = (q or "").strip()
    known = known_values(cx, field, taxa=taxa)
    out = []
    for entry in known.values():
        rank = match_rank(entry["value"], entry["note"], q)
        if rank is None:
            continue
        out.append((rank, -entry["n"], not entry["listed"], entry["value"].lower(),
                    dict(entry, rank=rank)))
    out.sort(key=lambda row: row[:4])
    return [row[4] for row in out[:limit]]


def import_terms(cx, field: str, lines) -> int:
    """Load a checklist. 'name' or 'name<TAB>anything you want shown beside it'."""
    n = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        value, _, note = line.partition("\t")
        cx.execute("INSERT INTO terms(field, value, note, from_list) VALUES(?,?,?,1) "
                   "ON CONFLICT(field, value) DO UPDATE SET note=excluded.note, from_list=1",
                   (field, value.strip(), note.strip()))
        n += 1
    cx.commit()
    return n
