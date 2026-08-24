"""Reading and writing the recorder's own fields.

Everything here is driven by the active profile, so nothing below knows or cares
what the fields are called. `_flag` is entolog's own, kept apart from the
recorder's fields by the leading underscore that profiles are not allowed to use.
"""

from __future__ import annotations

from . import profile as P

FLAG = "_flag"


def values(cx, photo_id: int) -> dict:
    return {r["field"]: r["value"] for r in cx.execute(
        "SELECT field, value FROM field_values WHERE photo_id=?", (photo_id,))}


def _attach(cx, rows):
    """One query for every value on the page, rather than one per photograph."""
    by_id = {r["id"]: r for r in rows}
    for r in rows:
        r["values"] = {}
        r["flagged"] = 0
    if by_id:
        marks = ",".join("?" * len(by_id))
        for v in cx.execute(
                f"SELECT photo_id, field, value FROM field_values WHERE photo_id IN ({marks})",
                tuple(by_id)):
            row = by_id[v["photo_id"]]
            if v["field"] == FLAG:
                row["flagged"] = 1 if v["value"] == "1" else 0
            else:
                row["values"][v["field"]] = v["value"]
    return rows


PHOTO_COLS = ("id, filename, rel_path, taken_at, taken_source, lat, lon, altitude, "
              "gridref, locality, orientation, camera, lens, width, height, group_id, "
              "seq, bytes, thumb_offset")


def list_photos(cx, prof, flt="all", q="", limit=5000) -> list:
    primary = prof["primary"]
    sql = [f"SELECT {','.join('p.' + c.strip() for c in PHOTO_COLS.split(','))} FROM photos p",
           "LEFT JOIN field_values pv ON pv.photo_id=p.id AND pv.field=?"]
    args = [primary]
    where = []
    if flt == "todo":
        where.append("COALESCE(pv.value,'')=''")
    elif flt == "done":
        where.append("COALESCE(pv.value,'')!=''")
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
    done = cx.execute("SELECT COUNT(*) c FROM field_values WHERE field=? AND value!=''",
                      (prof["primary"],)).fetchone()["c"]
    return {"total": total, "done": done}


def save(cx, prof, photo_id: int, fields: dict, apply_group=False) -> tuple:
    """Write one or more field values. Returns (photo ids touched, {field: error}).
    A value that fails its own rule is still stored: losing what someone typed is
    worse than storing something odd, and the window shows the complaint."""
    known = set(P.names(prof)) | {FLAG}
    errors, clean = {}, {}
    for k, v in fields.items():
        if k not in known:
            errors[k] = f"there is no field called {k!r} in the {prof['name']} profile"
            continue
        if k == FLAG:
            clean[k] = "1" if str(v) in ("1", "True", "true", "yes") else ""
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
    for t in targets:
        for k, v in clean.items():
            cx.execute(
                "INSERT INTO field_values(photo_id, field, value, updated_at) "
                "VALUES(?,?,?,datetime('now')) ON CONFLICT(photo_id, field) "
                "DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (t, k, v))
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


def suggest(cx, field: str, q: str = "", limit: int = 40) -> list:
    like = f"%{q}%"
    return [dict(r) for r in cx.execute(
        "SELECT value, note, uses FROM terms WHERE field=? AND (value LIKE ? OR note LIKE ?) "
        "ORDER BY uses DESC, value LIMIT ?", (field, like, like, limit))]


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
