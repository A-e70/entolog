from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import webbrowser
from pathlib import Path

from . import __version__, check as checkmod, clock, db, demo as demomod, entry, export
from . import locality, records, taxonomy
from . import scan as scanmod, server, tsvedit
from . import profile as P

DEFAULT_DB = "entolog.db"


def _db_for(args) -> Path:
    if args.db:
        return Path(args.db).expanduser()
    if os.environ.get("ENTOLOG_DB"):
        return Path(os.environ["ENTOLOG_DB"]).expanduser()
    here = Path(DEFAULT_DB)
    if here.exists():
        return here
    folders = getattr(args, "folders", None)
    if folders:
        root = Path(folders[0]).expanduser()
        return (root if root.is_dir() else root.parent) / DEFAULT_DB
    return here


def cmd_scan(args) -> int:
    dbpath = _db_for(args)
    cx = _connect(dbpath)
    print(f"reading {', '.join(args.folders)} -> {dbpath}")
    r = scanmod.scan(cx, args.folders, recursive=not args.flat, gap_seconds=args.gap,
                     progress=lambda n, f: print(f"  {n} photos… {f}", end="\r", flush=True))
    print(" " * 60, end="\r")
    print(f"{r['added']} new, {r['updated']} changed, {r['unchanged']} already known, "
          f"{r['recovered']} determinations followed a moved file")
    print(f"{r['groups']} specimen events (shots within {args.gap}s and 60 m of each other)")
    if r["missing"]:
        print(f"note: {r['missing']} photos in the database are no longer at their path")
    if not cx.execute("SELECT COUNT(*) c FROM photos").fetchone()["c"]:
        print(f"\nno photographs found in {', '.join(args.folders)}.", file=sys.stderr)
        print("entolog reads jpg, jpeg, png, tif, tiff, webp, heic and the usual raw "
              "files\n(nef, cr2, cr3, arw, raf, orf, rw2, dng and more). Check the "
              "folder, and\nremember it looks in subfolders unless you pass --flat.",
              file=sys.stderr)
        return 1
    print(export.summary(cx))
    return 0


def cmd_annotate(args) -> int:
    dbpath = _db_for(args)
    if not dbpath.exists():
        print(f"no database at {dbpath}. Run: entolog scan <folder>", file=sys.stderr)
        return 1
    httpd, url = server.serve(dbpath, port=args.port)
    # flush, so piping the output somewhere still shows the link
    print(f"entolog is at {url}", flush=True)
    print("keep this terminal open. Ctrl-C stops it. Work is saved as you type.",
          flush=True)
    if not args.no_open:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
        cx = _connect(dbpath)
        print(export.summary(cx))
    return 0


def cmd_export(args) -> int:
    cx = _connect(_db_for(args))
    cols = args.columns.split(",") if args.columns else None
    if args.format == "dwca":
        blob = export.dwca(cx, only_determined=not args.all)
        out = Path(args.out or "occurrences-dwca.zip")
        out.write_bytes(blob)
        print(f"wrote {out} ({len(blob) // 1024} KB): occurrence.csv, meta.xml, eml.xml")
        print("This is the file GBIF, the NBN Atlas and an IPT take. Set who made the "
              "records and the licence first if you have not:")
        print('  entolog set recorded_by "Your Name"    entolog set licence CC-BY')
        return 0
    text = export.render(cx, args.format, columns=cols, only_determined=not args.all)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out} ({text.count(chr(10)) - 1} rows)")
    else:
        sys.stdout.write(text)
    return 0


def cmd_stats(args) -> int:
    print(export.summary(db.connect(_db_for(args))))
    return 0


def cmd_terms(args) -> int:
    cx = _connect(_db_for(args))
    prof = P.active(cx)
    if args.field not in P.names(prof):
        print(f"the {prof['name']} profile has no field called {args.field!r}. "
              f"It has: {', '.join(P.names(prof))}", file=sys.stderr)
        return 1
    n = records.import_terms(cx, args.field,
                             Path(args.file).read_text(encoding="utf-8").splitlines())
    print(f"{n} entries ready to autocomplete in {args.field}")
    return 0


def cmd_backup(args) -> int:
    cx, _prof = _open(args)
    source = _db_for(args)
    out = Path(args.out).expanduser() if args.out else source.with_name(
        source.stem + "-backup" + source.suffix)
    if out.exists() and not args.force:
        print(f"{out} is already there. Pass --force to replace it.", file=sys.stderr)
        return 1
    try:
        with db.connect(out) as copy:
            cx.backup(copy)
    except (OSError, sqlite3.Error) as e:
        print(f"could not write {out}: {e}", file=sys.stderr)
        return 1
    size = out.stat().st_size
    print(f"copied {source} to {out} ({size // 1024} KB)")
    print("That file is the records. Keep it with the photographs.")
    return 0


def cmd_undo(args) -> int:
    cx, _prof = _open(args)
    if args.list:
        pending = records.pending_undo(cx)
        print(f"next undo puts back {pending['photos']} photographs: {pending['what']}"
              if pending else "nothing to undo")
        return 0
    done = records.undo(cx, args.times)
    if not done:
        print("nothing to undo")
        return 0
    for step in done:
        print(f"put back {step['photos']} photograph"
              f"{'s' if step['photos'] != 1 else ''}: {step['what']}")
    return 0


def cmd_time(args) -> int:
    cx, prof = _open(args)
    seconds = None
    if args.shift:
        try:
            seconds = clock.parse_shift(args.shift)
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 1
    elif args.set:
        target, _, when = args.set.partition("=")
        try:
            seconds = clock.offset_to(cx, entry.find(cx, target.strip()), when)
        except (LookupError, ValueError) as e:
            print(str(e), file=sys.stderr)
            return 1
        print(f"{target.strip()} is out by {clock.describe(seconds)}")
    elif args.from_gps:
        m = clock.against_gps(cx)
        if not m["photos"]:
            print("no photograph has both a camera time and a satellite fix, so "
                  "there is nothing to measure against.", file=sys.stderr)
            return 1
        try:
            zone = clock.zone_seconds(args.zone) if args.zone else m["nearest"]
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 1
        if not args.zone:
            print(f"assuming the time zone was {clock.describe(m['nearest'])}. "
                  f"Pass --zone to say otherwise.")
        seconds = -int(m["median"] - zone)
        if abs(seconds) < 2:
            print("the camera clock agrees with the satellites. Nothing to do.")
            return 0
    if seconds is None:
        m = clock.against_gps(cx)
        rows = cx.execute("SELECT taken_source, COUNT(*) c FROM photos "
                          "GROUP BY taken_source").fetchall()
        for row in rows:
            print(f"  {row['c']:>5}  {row['taken_source']}")
        if m["photos"]:
            print(f"\n{m['photos']} photographs carry a satellite fix as well as a "
                  f"camera time.")
            print(f"  the camera reads {clock.describe(m['median'])} against UTC")
            if m["spread"] > 120:
                print(f"  but not consistently: the difference varies by "
                      f"{clock.describe(m['spread'])}, so the clock may have been "
                      f"reset partway through")
            # Which part of that is the time zone is not in the file.
            for zone in m["zones"]:
                out = m["median"] - zone
                if abs(out) < 2:
                    print(f"  in a {clock.describe(zone)} zone the clock is right")
                else:
                    fast = "fast" if out > 0 else "slow"
                    print(f"  in a {clock.describe(zone)} zone the clock is "
                          f"{clock.describe(abs(out))[1:]} {fast}")
            print(f"\nCorrect it with the zone you were in:")
            print(f"  entolog time --from-gps --zone "
                  f"{clock.describe(m['zones'][0])}")
        else:
            print("\nNo photograph carries both a camera time and a satellite fix.")
            print("If you know what one photograph should say:")
            print("  entolog time --set 'IMG_0001.jpg=2026-06-14 09:26'")
        for past in clock.json_history(cx):
            print(f"already applied: {clock.describe(past['seconds'])} to "
                  f"{past['photos']} photographs")
        return 0

    if not args.yes:
        n = cx.execute("SELECT COUNT(*) c FROM photos WHERE taken_source LIKE 'exif%'"
                       if not args.all else "SELECT COUNT(*) c FROM photos").fetchone()["c"]
        print(f"about to move {n} photographs by {clock.describe(seconds)}")
        print("nothing is written to the photographs themselves, and the same "
              "command with the opposite sign undoes it.")
        try:
            if input("go ahead? [y/N] ").strip().lower() not in ("y", "yes"):
                print("left alone")
                return 0
        except EOFError:
            print("left alone")
            return 0
    result = clock.shift(cx, seconds, only_exif=not args.all)
    print(f"moved {result['photos']} photographs by {clock.describe(seconds)}, "
          f"{result['groups']} specimen events after regrouping")
    print(f"to undo: entolog time --shift {clock.describe(-seconds)} --yes")
    return 0


def cmd_taxa(args) -> int:
    cx, prof = _open(args)
    if args.action == "show":
        n = taxonomy.count(cx)
        if not n:
            print("no taxon list loaded. entolog ships none: bring the one you are "
                  "entitled to use.\n  entolog taxa import uksi.csv")
            return 0
        syn = cx.execute("SELECT COUNT(*) c FROM taxa WHERE accepted!=''").fetchone()["c"]
        with_id = cx.execute("SELECT COUNT(*) c FROM taxa WHERE taxon_id!=''").fetchone()["c"]
        print(f"{n} names, {syn} of them synonyms, {with_id} with a taxon identifier")
        for row in cx.execute("SELECT name, authority, rank, taxon_id, accepted, "
                              "vernacular FROM taxa ORDER BY name LIMIT 5"):
            bits = [row["name"]]
            if row["authority"]:
                bits.append(row["authority"])
            if row["vernacular"]:
                bits.append(f"({row['vernacular']})")
            if row["accepted"]:
                bits.append(f"-> {row['accepted']}")
            if row["taxon_id"]:
                bits.append(row["taxon_id"])
            print("  " + " ".join(bits))
        if n > 5:
            print(f"  and {n - 5} more")
        return 0
    if args.action == "clear":
        cx.execute("DELETE FROM taxa")
        cx.commit()
        print("taxon list cleared. Records are untouched.")
        return 0
    if not args.file:
        print("which file? entolog taxa import <file.csv>", file=sys.stderr)
        return 1
    text = sys.stdin.read() if args.file == "-" else \
        Path(args.file).read_text(encoding="utf-8-sig", errors="replace")
    result = taxonomy.load(cx, text, override=args.map, replace=not args.add)
    if result.get("problem"):
        print(result["problem"], file=sys.stderr)
        if result.get("columns"):
            print("understood: " + ", ".join(f"{k}={v}" for k, v in
                                             result["columns"].items()), file=sys.stderr)
        return 1
    print(f"{result['names']} names loaded"
          + (f", {result['synonyms']} of them synonyms" if result["synonyms"] else ""))
    print("columns read: " + ", ".join(f"{k} from {v!r}"
                                       for k, v in result["columns"].items()))
    missing = [k for k in ("taxon_id", "vernacular", "accepted") if k not in result["columns"]]
    if missing:
        print("not in this file: " + ", ".join(missing)
              + ". Pass --map name=column to point at a column entolog missed.")
    return 0


def cmd_profile(args) -> int:
    dbpath = _db_for(args)
    if args.action == "list":
        for name in P.BUILTIN:
            try:
                prof = P.load(name)
            except P.ProfileError as e:
                print(f"{name:10} cannot be loaded: {e}", file=sys.stderr)
                continue
            mark = ""
            if dbpath.exists():
                mark = "  <- in use" if P.active(db.connect(dbpath))["name"] == name else ""
            print(f"{name:10} {prof['title']}{mark}")
            print(f"{'':10} {', '.join(P.names(prof))}")
        return 0
    cx = _connect(dbpath)
    if args.action == "show":
        print(json.dumps(P.active(cx), indent=2))
        return 0
    if args.action == "use":
        if not args.name:
            print("which profile? A built-in name or a path to a .json file", file=sys.stderr)
            return 1
        try:
            prof = P.set_active(cx, args.name, force=args.force)
        except P.ProfileError as e:
            print(str(e), file=sys.stderr)
            return 1
        print(f"profile {prof['name']}: {', '.join(P.names(prof))}")
        moved = records.counts(cx, prof)
        print(f"{moved['done']}/{moved['total']} photographs have a {prof['primary']}")
        return 0
    if args.action == "check":
        try:
            prof = P.load(args.name) if args.name else P.active(cx)
        except P.ProfileError as e:
            print(str(e), file=sys.stderr)
            return 1
        print(f"{prof['name']} is usable: {len(prof['fields'])} fields, "
              f"primary {prof['primary']}")
        return 0
    return 1


SETTINGS = {
    "recorded_by": "who made the records, for recordedBy and identifiedBy",
    "licence": "CC0, CC-BY or CC-BY-NC. GBIF takes no others",
    "dataset_title": "what this set of records is called",
    "contact_email": "a contact address in the archive metadata",
    "abstract": "one paragraph about the dataset",
    "status_format": "the status line an image viewer shows",
    "blur": "publish every position as a square this size, unless a record says "
            "otherwise: 100m, 1km, 2km, 10km, 100km",
    "grid": "which grid reference system to use: auto, osgb, irish",
}


def cmd_set(args) -> int:
    cx = _connect(_db_for(args))
    if not args.key:
        for k, why in SETTINGS.items():
            print(f"  {k:15} {json.dumps(db.get_meta(cx, k, '')) :<28} {why}")
        return 0
    if args.key == "blur" and args.value and args.value not in locality.PRECISION_METRES:
        print("blur must be one of " + ", ".join(locality.PRECISION_METRES)
              + ", or empty for exact positions", file=sys.stderr)
        return 1
    if args.key == "grid" and args.value not in ("", "auto", "osgb", "irish"):
        print("grid must be auto, osgb or irish", file=sys.stderr)
        return 1
    if args.key == "licence" and args.value not in export.LICENCES:
        print(f"licence must be one of {', '.join(export.LICENCES)}. "
              f"GBIF will not register a dataset under anything else.", file=sys.stderr)
        return 1
    db.set_meta(cx, args.key, args.value)
    print(f"{args.key} = {args.value}")
    return 0


def _connect(dbpath: Path):
    """Open the record database, or explain why it cannot be opened. Pointing
    entolog at a memory card is the usual reason."""
    try:
        return db.connect(dbpath)
    except (OSError, sqlite3.OperationalError) as e:
        print(f"cannot open {dbpath}: {e}", file=sys.stderr)
        print("If the photographs are on a memory card or anywhere read only, "
              "keep the records elsewhere:", file=sys.stderr)
        print(f"  entolog --db ~/records/{dbpath.name} scan <folder>", file=sys.stderr)
        raise SystemExit(1)


def _open(args):
    dbpath = _db_for(args)
    if not dbpath.exists():
        print(f"no database at {dbpath}. Run: entolog scan <folder>", file=sys.stderr)
        raise SystemExit(1)
    cx = _connect(dbpath)
    return cx, P.active(cx)


def cmd_enter(args) -> int:
    cx, prof = _open(args)
    return entry.run(cx, prof, flt=args.filter, per_photo=args.per_photo,
                     follow=args.follow)


def cmd_line(args) -> int:
    cx, prof = _open(args)
    try:
        photo = entry.find(cx, args.target) if args.target else entry.get_current(cx)
    except LookupError as e:
        print(str(e), file=sys.stderr)
        return 1
    if photo is None:
        print("nothing is current. Pass a file, or use: entolog current <file>",
              file=sys.stderr)
        return 1
    print(entry.status_line(cx, prof, photo, fmt=args.format))
    return 0


def cmd_current(args) -> int:
    cx, prof = _open(args)
    try:
        photo = entry.set_current(cx, args.target)
    except LookupError as e:
        print(str(e), file=sys.stderr)
        return 1
    if not args.quiet:
        print(entry.status_line(cx, prof, photo, fmt=args.format))
    return 0


def cmd_record(args) -> int:
    cx, prof = _open(args)
    try:
        photo = entry.find(cx, args.target) if args.target != "-" else entry.get_current(cx)
    except LookupError as e:
        print(str(e), file=sys.stderr)
        return 1
    if photo is None:
        print("nothing is current", file=sys.stderr)
        return 1
    if args.precision is not None:
        _ids, errs = records.save(cx, prof, photo["id"],
                                  {records.PRECISION: args.precision}, apply_group=not args.photo)
        if errs:
            print("; ".join(errs.values()), file=sys.stderr)
            return 1
    if args.flag or args.unflag:
        records.save(cx, prof, photo["id"],
                     {records.FLAG: "1" if args.flag else ""}, apply_group=False)
        say, ids, errors = ["flagged" if args.flag else "unflagged"], [photo["id"]], {}
    elif not args.line:
        if args.precision is not None:
            print(entry.status_line(cx, prof, entry.find(cx, str(photo["id"])),
                                    fmt=args.format))
            return 0
        print("give something to record, or --flag, or --precision", file=sys.stderr)
        return 1
    else:
        say, ids, _clean, errors = entry.record_one(
            cx, prof, photo, " ".join(args.line), group=not args.photo)
    for line in say:
        print(line, file=sys.stderr if errors else sys.stdout)
    if errors:
        return 1
    print(entry.status_line(cx, prof, entry.find(cx, str(photo["id"])), fmt=args.format))
    return 0


def cmd_edit(args) -> int:
    cx, prof = _open(args)
    import subprocess
    import tempfile
    text = tsvedit.dump(cx, prof, flt=args.filter)
    editor = args.editor or os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
    with tempfile.NamedTemporaryFile("w+", suffix=".tsv", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(text)
        path = Path(fh.name)
    print(f"{editor} {path}")
    try:
        subprocess.call([*editor.split(), str(path)])
    except OSError as e:
        print(f"could not run {editor!r}: {e}", file=sys.stderr)
        return 1
    edited = path.read_text(encoding="utf-8")
    if edited == text:
        print("nothing changed")
        path.unlink(missing_ok=True)
        return 0
    print(tsvedit.summarise(tsvedit.apply(cx, prof, edited)))
    path.unlink(missing_ok=True)
    return 0


def cmd_apply(args) -> int:
    cx, prof = _open(args)
    text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
    print(tsvedit.summarise(tsvedit.apply(cx, prof, text)))
    return 0


def cmd_table(args) -> int:
    cx, prof = _open(args)
    text = tsvedit.dump(cx, prof, flt=args.filter, context=not args.bare)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        sys.stdout.write(text)
    return 0


def cmd_locality(args) -> int:
    cx, _prof = _open(args)
    parts = args.parts
    if args.action == "list":
        rows = cx.execute("SELECT key, short, verbose FROM places ORDER BY short").fetchall()
        for r in rows:
            print(f"{r['key']:>22}  {r['short']}")
        missing = locality.pending(cx)
        print(f"{len(rows)} places named, {len(missing)} positions still unnamed"
              + (f" ({sum(m['n'] for m in missing)} photographs)" if missing else ""))
        return 0
    if args.action == "shorten":
        n = locality.reshorten(cx, parts)
        print(f"re-shortened to {parts} part(s), {n} photographs updated")
        return 0
    if args.action == "import":
        text = sys.stdin.read() if args.file in (None, "-") else \
            Path(args.file).read_text(encoding="utf-8")
        done = bad = 0
        for line in text.splitlines():
            line = line.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            cells = [c.strip() for c in line.split("\t")]
            try:
                if len(cells) >= 3 and _isnum(cells[0]) and _isnum(cells[1]):
                    locality.store(cx, float(cells[0]), float(cells[1]),
                                   "\t".join(cells[2:]), parts)
                elif len(cells) >= 2:
                    photo = entry.find(cx, cells[0])
                    if photo["lat"] is None:
                        bad += 1
                        continue
                    locality.store(cx, photo["lat"], photo["lon"],
                                   "\t".join(cells[1:]), parts)
                else:
                    bad += 1
                    continue
                done += 1
            except (LookupError, ValueError):
                bad += 1
        cx.commit()
        n = locality.apply_to_photos(cx)
        print(f"{done} places stored, {n} photographs named"
              + (f", {bad} lines could not be used" if bad else ""))
        return 0
    if args.action == "lookup":
        todo = locality.pending(cx)[:args.limit] if args.limit else locality.pending(cx)
        if not todo:
            print("every position already has a name")
            return 0
        print(f"asking OpenStreetMap about {len(todo)} position(s), one a second. "
              f"This is the only part of entolog that uses the network.")
        for i, place in enumerate(todo, 1):
            try:
                data = locality.lookup(place["lat"], place["lon"], email=args.email)
            except Exception as e:                     # network, rate limit, anything
                print(f"stopped after {i - 1}: {e}", file=sys.stderr)
                break
            short = locality.store(cx, place["lat"], place["lon"], data, parts, "osm")
            print(f"  {place['place_key']}  {short}   ({place['n']} photographs)")
        cx.commit()
        n = locality.apply_to_photos(cx)
        print(f"{n} photographs named")
        return 0
    return 1


def _isnum(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def cmd_check(args) -> int:
    cx, prof = _open(args)
    findings = checkmod.run(cx, prof)
    if args.json:
        print(json.dumps(findings, indent=2))
    else:
        print(checkmod.report(findings))
    return 1 if any(f["level"] == "error" for f in findings) else 0


def cmd_demo(args) -> int:
    folder = Path(args.folder).expanduser()
    if folder.exists() and any(folder.iterdir()) and not args.force:
        print(f"{folder} is not empty. Pass --force, or give another folder.",
              file=sys.stderr)
        return 1
    made = demomod.build(folder)
    print(f"{len(made['photos'])} demo photographs in {folder}")
    dbpath = folder / DEFAULT_DB
    cx = _connect(dbpath)
    scanmod.scan(cx, [folder])
    records.import_terms(cx, "species",
                         [f"{n}\t{v}" for n, v in demomod.CHECKLIST])
    db.set_meta(cx, "recorded_by", "A Naturalist")
    prof = P.active(cx)
    ids = [r["id"] for r in cx.execute("SELECT id FROM photos ORDER BY seq")]
    entry.record_one(cx, prof, entry.find(cx, str(ids[0])),
                     "Vespa crabro / adult / f / on ivy, sunny bank", group=True)
    entry.record_one(cx, prof, entry.find(cx, str(ids[4])),
                     "Bombus terrestris / adult / worker / on bramble", group=True)
    # One photograph deliberately holds two things, because a real card does.
    entry.record_one(cx, prof, entry.find(cx, str(ids[4])),
                     "Episyrphus balteatus / adult / / on the same flower",
                     group=False, occ=2)
    # The whole walk is in one wood, so give every position the same name rather
    # than only the one the walk started from.
    for place in locality.pending(cx):
        locality.store(cx, place["lat"], place["lon"],
                       "Wytham Woods, Wytham, Vale of White Horse, Oxfordshire, "
                       "England, OX2 8QQ, United Kingdom", source="demo")
    locality.apply_to_photos(cx)
    print(f"scanned into {dbpath}, two specimen events already recorded, "
          f"{len(demomod.CHECKLIST)} names loaded for autocomplete")
    print("")
    print("Try any of these:")
    print(f"  entolog --db {dbpath} annotate      the window")
    print(f"  entolog --db {dbpath} enter         the terminal")
    print(f"  entolog --db {dbpath} edit          the table in $EDITOR")
    print(f"  entolog --db {dbpath} check         the record cleaning pass")
    print(f"  entolog --db {dbpath} time          the camera clock, which on this "
          f"card is wrong")
    print(f"  entolog --db {dbpath} export -f dwca -o records.zip")
    print("")
    print("The pictures are drawings, not photographs. Everything else is real.")
    if args.no_open:
        return 0
    args.db, args.port, args.no_open = str(dbpath), args.port, False
    return cmd_annotate(args)


def cmd_doctor(args) -> int:
    import shutil
    import socket
    ok = True
    print(f"entolog {__version__}")
    print(f"  python        {sys.version.split()[0]}  ({sys.executable})")
    if sys.version_info < (3, 9):
        print("                 too old, entolog needs 3.9 or newer")
        ok = False
    here = Path(__file__).resolve()
    print(f"  running from  {'a single file bundle' if '.pyz' in str(here) else here.parent}")
    try:
        import PIL
        print(f"  pillow        {PIL.__version__}, so raw files can be previewed")
    except ImportError:
        print("  pillow        not installed. Only needed to preview raw files "
              "a browser cannot show")
    exif = ("found" if shutil.which("exiftool") else
            "not installed. Only used as a second opinion on HEIC and unusual raws")
    print(f"  exiftool      {exif}")
    try:
        import readline                                    # noqa: F401
        print("  readline      yes, so the terminal has history and tab completion")
    except ImportError:
        print("  readline      missing, so no tab completion in the terminal")
    dbpath = _db_for(args)
    print(f"  database      {dbpath}" + ("" if dbpath.exists() else "  (not made yet)"))
    if dbpath.exists():
        try:
            cx = _connect(dbpath)
            prof = P.active(cx)
            c = records.counts(cx, prof)
            print(f"  profile       {prof['name']}: {', '.join(P.names(prof))}")
            print(f"  records       {c['done']} of {c['total']} photographs")
        except Exception as e:
            print(f"                 cannot be opened: {e}")
            ok = False
    folder = dbpath.parent
    print(f"  writable      {'yes' if os.access(folder, os.W_OK) else 'NO, ' + str(folder)}")
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 8731))
        print("  port 8731     free")
    except OSError:
        print("  port 8731     in use, so the window will pick the next free one")
    finally:
        s.close()
    print("\n" + ("everything needed is here" if ok else "something above needs fixing"))
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="entolog",
        description="Turn a folder of insect photographs into a species record table. "
                    "The file gives the date and the position, you give the determination.")
    p.add_argument("--version", action="version", version=f"entolog {__version__}")
    p.add_argument("--db", help=f"record database (default {DEFAULT_DB} beside the photos)")
    # --db is accepted either before or after the subcommand; SUPPRESS keeps the
    # subcommand's copy from blanking a value given at the top level.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    sub = p.add_subparsers(dest="cmd", parser_class=lambda **kw: argparse.ArgumentParser(
        parents=[common], **kw))

    s = sub.add_parser("scan", help="read a folder of photos into the database")
    s.add_argument("folders", nargs="+")
    s.add_argument("--gap", type=int, default=150,
                   help="seconds between shots before a new specimen event starts (default 150)")
    s.add_argument("--flat", action="store_true", help="do not descend into subfolders")
    s.set_defaults(func=cmd_scan)

    a = sub.add_parser("annotate", aliases=["ui"], help="open the determination window")
    a.add_argument("--port", type=int, default=8731)
    a.add_argument("--no-open", action="store_true")
    a.set_defaults(func=cmd_annotate)

    e = sub.add_parser("export", help="write the table out")
    e.add_argument("-f", "--format", default="csv",
                   choices=["csv", "tsv", "full", "dwc", "dwca", "irecord",
                            "json", "geojson", "md"])
    e.add_argument("-o", "--out")
    e.add_argument("--columns", help="comma separated column list for csv/tsv")
    e.add_argument("--all", action="store_true", help="include photos with no species yet")
    e.set_defaults(func=cmd_export)

    sub.add_parser("stats", help="how far through the folder you are").set_defaults(func=cmd_stats)

    sp = sub.add_parser("terms", aliases=["species"],
                        help="load a checklist into a field for autocomplete")
    sp.add_argument("field", nargs="?", default="species",
                    help="which field the list belongs to (default species)")
    sp.add_argument("file", help="one entry per line, or 'entry<TAB>note'")
    sp.set_defaults(func=cmd_terms)

    pr = sub.add_parser("profile", help="which fields a record has")
    pr.add_argument("action", choices=["list", "show", "use", "check"])
    pr.add_argument("name", nargs="?", help="built-in name or path to a .json profile")
    pr.add_argument("--force", action="store_true",
                    help="adopt it even though fields holding records would be dropped")
    pr.set_defaults(func=cmd_profile)

    en = sub.add_parser("enter", aliases=["type"],
                        help="record from the keyboard, no window needed")
    en.add_argument("--filter", default="todo",
                    choices=["todo", "all", "done", "flagged", "nogps"])
    en.add_argument("--per-photo", action="store_true",
                    help="one record per photograph instead of per specimen event")
    en.add_argument("--follow", action="store_true",
                    help="track whatever your image viewer says it is showing")
    en.set_defaults(func=cmd_enter)

    ln = sub.add_parser("line", help="one status line for an image viewer to display")
    ln.add_argument("target", nargs="?", help="path, filename or number. Default: current")
    ln.add_argument("--format", help="e.g. '{filename} {date} {gridref} | {record}'")
    ln.set_defaults(func=cmd_line)

    cu = sub.add_parser("current", help="tell entolog which photograph is being viewed")
    cu.add_argument("target")
    cu.add_argument("--format")
    cu.add_argument("-q", "--quiet", action="store_true")
    cu.set_defaults(func=cmd_current)

    rc = sub.add_parser("record", help="record one photograph in one command")
    rc.add_argument("target", help="path, filename, number, or - for the current one")
    rc.add_argument("line", nargs="*", help="e.g. 'Vespa crabro / adult / f / on ivy'")
    rc.add_argument("--flag", action="store_true", help="mark for a second look")
    rc.add_argument("--precision", help="publish this record only as a square "
                                        "this size: 100m, 1km, 2km, 10km, 100km")
    rc.add_argument("--unflag", action="store_true")
    rc.add_argument("--photo", action="store_true",
                    help="this photograph only, not the whole specimen event")
    rc.add_argument("--format")
    rc.set_defaults(func=cmd_record)

    ed = sub.add_parser("edit", help="edit the whole table in $EDITOR and read it back")
    ed.add_argument("--filter", default="all",
                    choices=["todo", "all", "done", "flagged", "nogps"])
    ed.add_argument("--editor")
    ed.set_defaults(func=cmd_edit)

    ap = sub.add_parser("apply", help="read an edited table back in")
    ap.add_argument("file", help="a tab separated file, or - for standard input")
    ap.set_defaults(func=cmd_apply)

    tb = sub.add_parser("table", help="write the editable table out")
    tb.add_argument("-o", "--out")
    tb.add_argument("--bare", action="store_true", help="editable columns only")
    tb.add_argument("--filter", default="all",
                    choices=["todo", "all", "done", "flagged", "nogps"])
    tb.set_defaults(func=cmd_table)

    ck = sub.add_parser("check", help="look for the problems a scheme would send back")
    ck.add_argument("--json", action="store_true")
    ck.set_defaults(func=cmd_check)

    dm = sub.add_parser("demo", help="make a folder of demo photographs and open it")
    dm.add_argument("folder", nargs="?", default="entolog-demo")
    dm.add_argument("--force", action="store_true", help="use the folder even if it has files in")
    dm.add_argument("--no-open", action="store_true")
    dm.add_argument("--port", type=int, default=8731)
    dm.set_defaults(func=cmd_demo)

    dr = sub.add_parser("doctor", help="check this machine can run everything")
    dr.set_defaults(func=cmd_doctor)

    bk = sub.add_parser("backup", help="copy the records somewhere safe")
    bk.add_argument("out", nargs="?", help="where to write it")
    bk.add_argument("--force", action="store_true")
    bk.set_defaults(func=cmd_backup)

    un = sub.add_parser("undo", help="put back the last change")
    un.add_argument("-n", "--times", type=int, default=1)
    un.add_argument("--list", action="store_true", help="say what would be put back")
    un.set_defaults(func=cmd_undo)

    tm = sub.add_parser("time", help="check or correct the camera clock")
    tm.add_argument("--shift", help="move every date, e.g. +3h12m or -45m")
    tm.add_argument("--set", help="'IMG_0001.jpg=2026-06-14 09:26', and everything "
                                  "else moves by the same amount")
    tm.add_argument("--zone", help="the time zone the camera was set to, e.g. +1h")
    tm.add_argument("--from-gps", action="store_true",
                    help="measure the error against the satellite clock and correct it")
    tm.add_argument("--all", action="store_true",
                    help="include photographs dated from the file rather than the EXIF")
    tm.add_argument("-y", "--yes", action="store_true", help="do not ask")
    tm.set_defaults(func=cmd_time)

    tx = sub.add_parser("taxa", help="load the taxon list you are entitled to use")
    tx.add_argument("action", choices=["import", "show", "clear"])
    tx.add_argument("file", nargs="?", help="csv or tab separated, or - for stdin")
    tx.add_argument("--map", help="point at columns entolog missed, "
                                  "e.g. name=Taxon,taxon_id=TVK")
    tx.add_argument("--add", action="store_true",
                    help="add to the list already loaded instead of replacing it")
    tx.set_defaults(func=cmd_taxa)

    lo = sub.add_parser("locality", help="turn a position into a place name")
    lo.add_argument("action", choices=["list", "import", "lookup", "shorten"])
    lo.add_argument("file", nargs="?",
                    help="for import: 'lat<TAB>lon<TAB>name' or 'filename<TAB>name', "
                         "or - for standard input")
    lo.add_argument("--parts", type=int, default=2,
                    help="how many parts of the name to keep (default 2)")
    lo.add_argument("--limit", type=int, help="for lookup: stop after this many")
    lo.add_argument("--email", default="",
                    help="for lookup: OpenStreetMap ask for a contact address")
    lo.set_defaults(func=cmd_locality)

    st = sub.add_parser("set", help="store a setting, e.g. set recorded_by 'A Naturalist'")
    st.add_argument("key", nargs="?")
    st.add_argument("value", nargs="?", default="")
    st.set_defaults(func=cmd_set)
    return p


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # `entolog ~/photos/june` with no subcommand means scan then annotate.
    if argv and not argv[0].startswith("-") and Path(argv[0]).expanduser().exists():
        args = build_parser().parse_args(["scan"] + argv)
        if cmd_scan(args) != 0:
            return 1
        return cmd_annotate(build_parser().parse_args(
            ["annotate"] + (["--db", str(_db_for(args))])))
    if not argv:
        print(FIRST_RUN.format(version=__version__))
        return 0
    args = build_parser().parse_args(argv)
    if not getattr(args, "func", None):
        build_parser().print_help()
        return 0
    return args.func(args)


FIRST_RUN = """entolog {version}, photographs to a species record table

Two ways to start:

  entolog demo                 try it on 21 demo photographs, no camera needed
  entolog ~/photos/june        read your own folder and open the window

Once a folder has been read:

  entolog enter                record from the keyboard, no window
  entolog edit                 the whole table in $EDITOR
  entolog undo                 put back the last change

Before you send anything:

  entolog taxa import <list>   your own taxon list, so names carry an identifier
  entolog time                 is the camera clock right? Measured against the GPS
  entolog check                the problems a recording scheme would send back
  entolog export -f dwca -o records.zip     a Darwin Core Archive

  entolog profile list         the fields a record has, and how to change them
  entolog --help               every command
  entolog doctor               check this machine has what it needs
"""
