from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path

from . import __version__, db, export, records, scan as scanmod, server
from . import profile as P

DEFAULT_DB = "entolog.db"


def _db_for(args) -> Path:
    if args.db:
        return Path(args.db).expanduser()
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
    cx = db.connect(dbpath)
    print(f"reading {', '.join(args.folders)} -> {dbpath}")
    r = scanmod.scan(cx, args.folders, recursive=not args.flat, gap_seconds=args.gap,
                     progress=lambda n, f: print(f"  {n} photos… {f}", end="\r", flush=True))
    print(" " * 60, end="\r")
    print(f"{r['added']} new, {r['updated']} changed, {r['unchanged']} already known, "
          f"{r['recovered']} determinations followed a moved file")
    print(f"{r['groups']} specimen events (shots within {args.gap}s and 60 m of each other)")
    if r["missing"]:
        print(f"note: {r['missing']} photos in the database are no longer at their path")
    print(export.summary(cx))
    return 0


def cmd_annotate(args) -> int:
    dbpath = _db_for(args)
    if not dbpath.exists():
        print(f"no database at {dbpath}. Run: entolog scan <folder>", file=sys.stderr)
        return 1
    httpd, url = server.serve(dbpath, port=args.port)
    print(f"entolog is at {url}")
    print("keep this terminal open. Ctrl-C stops it. Work is saved as you type.")
    if not args.no_open:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
        cx = db.connect(dbpath)
        print(export.summary(cx))
    return 0


def cmd_export(args) -> int:
    cx = db.connect(_db_for(args))
    cols = args.columns.split(",") if args.columns else None
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
    cx = db.connect(_db_for(args))
    prof = P.active(cx)
    if args.field not in P.names(prof):
        print(f"the {prof['name']} profile has no field called {args.field!r}. "
              f"It has: {', '.join(P.names(prof))}", file=sys.stderr)
        return 1
    n = records.import_terms(cx, args.field,
                             Path(args.file).read_text(encoding="utf-8").splitlines())
    print(f"{n} entries ready to autocomplete in {args.field}")
    return 0


def cmd_profile(args) -> int:
    dbpath = _db_for(args)
    if args.action == "list":
        for name in P.BUILTIN:
            prof = P.load(name)
            mark = ""
            if dbpath.exists():
                mark = "  <- in use" if P.active(db.connect(dbpath))["name"] == name else ""
            print(f"{name:10} {prof['title']}{mark}")
            print(f"{'':10} {', '.join(P.names(prof))}")
        return 0
    cx = db.connect(dbpath)
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


def cmd_set(args) -> int:
    cx = db.connect(_db_for(args))
    db.set_meta(cx, args.key, args.value)
    print(f"{args.key} = {args.value}")
    return 0


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
                   choices=["csv", "tsv", "full", "dwc", "json", "geojson", "md"])
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

    st = sub.add_parser("set", help="store a setting, e.g. set recorded_by 'A Naturalist'")
    st.add_argument("key")
    st.add_argument("value")
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
    args = build_parser().parse_args(argv)
    if not getattr(args, "func", None):
        build_parser().print_help()
        return 0
    return args.func(args)
