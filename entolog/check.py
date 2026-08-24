"""A record cleaning pass, run against your own database before anything leaves it.

Recording schemes run their own checks when you submit. This finds the same
things first, offline, while the photographs are still in front of you: a name
typed two ways, a camera clock that was never set, a record with no position, a
value that is not in the checklist you loaded.

Nothing here changes a record. It only reports.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from . import records, taxonomy
from . import profile as P

ERROR, WARNING, NOTE = "error", "warning", "note"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _close(a: str, b: str, limit: int = 1) -> bool:
    """Levenshtein distance no greater than limit, given up on early."""
    if abs(len(a) - len(b)) > limit:
        return False
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > limit:
            return False
        prev = cur
    return prev[-1] <= limit


def run(cx, prof=None) -> list:
    """Returns findings, worst first. Each is a dict the caller can print or
    serialise: level, code, message, and the photographs it concerns."""
    prof = prof or P.active(cx)
    primary = prof["primary"]
    found = []

    def plural(n, word):
        return f"{n} {word}{'s' if n != 1 else ''}"

    def add(level, code, message, rows=(), hint=""):
        found.append({"level": level, "code": code, "message": message,
                      "hint": hint,
                      "photos": [{"id": r["id"], "filename": r["filename"]}
                                 for r in rows][:200],
                      "count": len(rows)})

    photos = records.list_photos(cx, prof, "all", limit=10 ** 9)
    # One entry per record, not per photograph: a light trap photograph can hold
    # several, and each is checked on its own.
    recorded = []
    for p in photos:
        for occ, vals, _flag, _prec in records.each_record(p):
            if vals.get(primary):
                entry = dict(p)
                entry["values"] = vals
                entry["occ"] = occ
                recorded.append(entry)

    # --- the record cannot be used without these -------------------------
    no_place = [p for p in recorded if p["lat"] is None and not p["gridref"]]
    if no_place:
        add(ERROR, "no-position", f"{len(no_place)} records have no position",
            no_place, "Add a grid reference by hand, or use the 'no position' filter")

    now = datetime.now()
    future, ancient, from_file = [], [], []
    for p in recorded:
        if p["taken_source"] != "exif":
            from_file.append(p)
        try:
            when = datetime.fromisoformat((p["taken_at"] or "")[:19])
        except ValueError:
            continue
        if when > now + timedelta(days=1):
            future.append(p)
        elif when.year < 1995:
            ancient.append(p)
    if future:
        add(ERROR, "date-in-future", f"{len(future)} records are dated in the future",
            future, "The camera clock is wrong. Fix it before the next outing")
    if ancient:
        add(ERROR, "date-implausible",
            f"{len(ancient)} records are dated before 1995, which no digital camera was",
            ancient, "The camera clock was reset, usually by a flat battery")

    for f in prof["fields"]:
        if not f["required"]:
            continue
        empty = [p for p in recorded if not p["values"].get(f["name"])]
        if empty:
            add(ERROR, "required-empty",
                f"{len(empty)} records have no {f['label']}, which this profile requires",
                empty)

    # --- probably wrong ---------------------------------------------------
    bad = {}
    for p in recorded:
        for name, value in p["values"].items():
            if not value:
                continue
            _v, err = P.clean(prof, name, value)
            if err:
                bad.setdefault(f"{name}: {err}", []).append(p)
    for message, rows in bad.items():
        add(WARNING, "invalid-value", f"{len(rows)} records have {message}", rows)

    values = {}
    for p in recorded:
        v = p["values"].get(primary, "")
        values.setdefault(v, []).append(p)
    groups = {}
    for v in values:
        groups.setdefault(_norm(v), []).append(v)
    for norm, spellings in groups.items():
        if len(spellings) > 1:
            rows = [p for v in spellings for p in values[v]]
            add(WARNING, "same-name-two-ways",
                f"{primary} written {len(spellings)} ways: "
                + ", ".join(repr(s) for s in sorted(spellings)), rows,
                "Only spacing or capitals differ, so these are one name")
    seen = sorted(groups)
    for i, a in enumerate(seen):
        for b in seen[i + 1:]:
            if len(a) > 5 and _close(a, b) and a != b:
                rows = [p for v in groups[a] + groups[b] for p in values[v]]
                add(WARNING, "names-nearly-the-same",
                    f"{groups[a][0]!r} and {groups[b][0]!r} differ by one letter", rows,
                    "One of them may be a typo. Both may also be real")

    has_taxa = taxonomy.count(cx) > 0
    for f in prof["fields"]:
        if has_taxa and f["name"] == primary:
            continue                 # the taxon list is the authority for names
        listed = {r["value"] for r in cx.execute(
            "SELECT value FROM terms WHERE field=? AND from_list=1", (f["name"],))}
        if not listed:
            continue
        off = [p for p in recorded
               if p["values"].get(f["name"]) and p["values"][f["name"]] not in listed]
        if off:
            names = sorted({p["values"][f["name"]] for p in off})
            add(WARNING, "not-in-checklist",
                f"{len(off)} records have a {f['label']} that is not in your checklist: "
                + ", ".join(repr(n) for n in names[:6])
                + (f" and {len(names) - 6} more" if len(names) > 6 else ""), off)

    if taxonomy.count(cx):
        unknown, synonyms = [], {}
        for p in recorded:
            name = p["values"].get(primary, "")
            got = taxonomy.lookup(cx, name)
            if got is None:
                unknown.append(p)
            elif got["accepted"]:
                synonyms.setdefault((name, got["accepted"]), []).append(p)
        if unknown:
            names = sorted({p["values"][primary] for p in unknown})
            add(WARNING, "not-in-taxon-list",
                f"{len(unknown)} records use a name your taxon list does not have: "
                + ", ".join(repr(n) for n in names[:6])
                + (f" and {len(names) - 6} more" if len(names) > 6 else ""), unknown,
                "A scheme will have to match these by hand, or send them back")
        for (name, accepted), rows in synonyms.items():
            add(WARNING, "recorded-under-a-synonym",
                f"{len(rows)} records are under {name!r}, which your list calls a "
                f"synonym of {accepted!r}", rows,
                "Both names export, with acceptedNameUsage saying which is which")

    # --- worth a look -----------------------------------------------------
    if from_file:
        add(NOTE, "date-from-file",
            f"{len(from_file)} records take their date from the file, not the EXIF",
            from_file, "Editing or copying a photograph can lose the original date")

    # Only the first record on each photograph: a photograph deliberately
    # holding two species is not a disagreement about one specimen.
    by_event = {}
    for p in recorded:
        if p.get("occ", 1) == 1:
            by_event.setdefault(p["group_id"], set()).add(p["values"].get(primary, ""))
    mixed = [g for g, names in by_event.items() if len(names) > 1]
    if mixed:
        rows = [p for p in recorded if p["group_id"] in mixed]
        add(NOTE, "event-has-two-names",
            plural(len(mixed), "specimen event") + f" holds more than one {primary}", rows,
            "Fine if the burst really caught two things")

    flagged = [p for p in photos if p["flagged"]]
    if flagged:
        add(NOTE, "still-flagged", plural(len(flagged), "photograph") + " still flagged", flagged)

    todo = [p for p in photos
            if not any(v.get(primary) for _o, v, _f, _pr in records.each_record(p))]
    if todo:
        add(NOTE, "not-recorded-yet",
            f"{len(todo)} of {len(photos)} photographs have no {primary} yet", todo)

    order = {ERROR: 0, WARNING: 1, NOTE: 2}
    return sorted(found, key=lambda f: (order[f["level"]], -f["count"]))


MARK = {ERROR: "!", WARNING: "?", NOTE: "-"}


def report(findings, show=4) -> str:
    if not findings:
        return "nothing to report. Every record has a name, a date and a position."
    out = []
    for f in findings:
        out.append(f"{MARK[f['level']]} {f['message']}")
        if f["hint"]:
            out.append(f"    {f['hint']}")
        names = ", ".join(p["filename"] for p in f["photos"][:show])
        if names:
            out.append(f"    {names}" + (f" and {f['count'] - show} more"
                                         if f["count"] > show else ""))
    counts = {}
    for f in findings:
        counts[f["level"]] = counts.get(f["level"], 0) + 1
    out.append("")
    out.append(", ".join(f"{n} {level}{'s' if n != 1 else ''}"
                         for level, n in counts.items()))
    return "\n".join(out)
