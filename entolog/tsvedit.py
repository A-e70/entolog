"""The table as a file you can edit in vim, and read back.

Columns are matched by their header name, so the file can be reordered, cut down
to two columns, or sorted, and it still applies. Anything not in the file is left
alone: deleting a row from the file does not delete the record.
"""

from __future__ import annotations

from . import export, records
from . import profile as P

KEY = "id"
OCC = "record"
NOTE = ("# entolog table. Edit the fields, save, quit.\n"
        "# Columns are matched by name, so you may reorder or delete columns.\n"
        "# {key} is read only and says which photograph a row belongs to.\n"
        "# Deleting a row here does not delete the record, it just leaves it alone.\n"
        "# Read only from here on: {ro}\n")


def esc(v) -> str:
    return ("" if v is None else str(v)).replace("\\", "\\\\").replace(
        "\t", "\\t").replace("\n", "\\n").replace("\r", "")


def unesc(v: str) -> str:
    out, i = [], 0
    while i < len(v):
        c = v[i]
        if c == "\\" and i + 1 < len(v):
            nxt = v[i + 1]
            out.append({"t": "\t", "n": "\n", "\\": "\\"}.get(nxt, "\\" + nxt))
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


CONTEXT = ("filename", "date", "time", "locality", "gridref", "latitude", "longitude", "group")


def dump(cx, prof=None, flt="all", context=True) -> str:
    prof = prof or P.active(cx)
    editable = P.names(prof)
    several = any(r["occs"] > 1 for r in records.list_photos(cx, prof, flt, limit=10 ** 9))
    cols = [KEY] + ([OCC] if several else []) + editable + \
        (list(CONTEXT) if context else [])
    lines = [NOTE.format(key=KEY, ro=", ".join(CONTEXT) if context else "none").rstrip("\n"),
             "\t".join(cols)]
    for r in records.list_photos(cx, prof, flt, limit=10 ** 9):
        for occ, vals, _flag, _prec in records.each_record(r):
            d = export.photo_part(r)
            d.update(vals)
            d[KEY] = r["id"]
            d[OCC] = occ
            lines.append("\t".join(esc(d.get(c, "")) for c in cols))
    return "\n".join(lines) + "\n"


def apply(cx, prof=None, text: str = "") -> dict:
    """Read an edited table back. Nothing is deleted and nothing is guessed."""
    prof = prof or P.active(cx)
    editable = set(P.names(prof))
    report = {"rows": 0, "changed": 0, "fields": 0, "unknown_rows": [], "problems": [],
              "ignored_columns": []}
    header, body = None, []
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if header is None:
            header = [c.strip() for c in raw.split("\t")]
            continue
        body.append(raw)
    if header is None:
        report["problems"].append("the file has no header row")
        return report
    if KEY not in header:
        report["problems"].append(f"the header has no {KEY!r} column, so rows cannot be "
                                  f"matched to photographs")
        return report
    key_at = header.index(KEY)
    occ_at = header.index(OCC) if OCC in header else None
    use = [(i, name) for i, name in enumerate(header) if name in editable]
    report["ignored_columns"] = [c for c in header
                                if c not in editable and c not in (KEY, OCC)]
    if not use:
        report["problems"].append("no editable columns in the header: "
                                  + ", ".join(sorted(editable)))
        return report

    batch = records.next_batch(cx)
    for n, raw in enumerate(body, 2):
        cells = [unesc(c) for c in raw.split("\t")]
        if key_at >= len(cells) or not cells[key_at].strip():
            report["problems"].append(f"line {n}: no {KEY}, skipped")
            continue
        try:
            pid = int(cells[key_at])
        except ValueError:
            report["problems"].append(f"line {n}: {cells[key_at]!r} is not an {KEY}")
            continue
        row = cx.execute("SELECT id FROM photos WHERE id=?", (pid,)).fetchone()
        if row is None:
            report["unknown_rows"].append(pid)
            continue
        occ = 1
        if occ_at is not None and occ_at < len(cells) and cells[occ_at].strip():
            try:
                occ = max(1, int(cells[occ_at]))
            except ValueError:
                report["problems"].append(f"line {n}: {cells[occ_at]!r} is not a "
                                          f"record number")
                continue
        report["rows"] += 1
        before = records.values(cx, pid, occ)
        change = {}
        for i, name in use:
            if i >= len(cells):
                continue                      # column not present on this line: unchanged
            v = cells[i].strip()
            if v != (before.get(name, "") or ""):
                change[name] = v
        if not change:
            continue
        _ids, errors = records.save(cx, prof, pid, change, apply_group=False,
                                    batch=batch, occ=occ)
        for f, e in errors.items():
            report["problems"].append(f"line {n}, {f}: {e}")
        report["changed"] += 1
        report["fields"] += len(change)
    return report


def summarise(report) -> str:
    bits = [f"{report['changed']} of {report['rows']} rows changed, "
            f"{report['fields']} values written"]
    if report["ignored_columns"]:
        bits.append("read only columns ignored: " + ", ".join(report["ignored_columns"]))
    if report["unknown_rows"]:
        bits.append(f"{len(report['unknown_rows'])} rows had an id not in this database: "
                    + ", ".join(str(i) for i in report["unknown_rows"][:8]))
    bits += report["problems"][:20]
    if len(report["problems"]) > 20:
        bits.append(f"and {len(report['problems']) - 20} more problems")
    return "\n".join(bits)
