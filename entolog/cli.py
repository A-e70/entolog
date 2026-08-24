from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from . import __version__, db, export, scan as scanmod, server

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


def cmd_species(args) -> int:
    cx = db.connect(_db_for(args))
    names = [n.strip() for n in Path(args.file).read_text(encoding="utf-8").splitlines() if n.strip()]
    for n in names:
        parts = [p.strip() for p in n.split("\t")] if "\t" in n else [n, ""]
        cx.execute("INSERT INTO species(name, vernacular, from_list) VALUES(?,?,1) "
                   "ON CONFLICT(name) DO UPDATE SET vernacular=excluded.vernacular, from_list=1",
                   (parts[0], parts[1] if len(parts) > 1 else ""))
    cx.commit()
    print(f"{len(names)} names available for autocomplete")
    return 0


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

    sp = sub.add_parser("species", help="load a checklist for autocomplete (one name per line)")
    sp.add_argument("file")
    sp.set_defaults(func=cmd_species)

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
