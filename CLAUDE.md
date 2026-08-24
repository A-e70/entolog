# entolog

Photographs of insects to a species record table. Written for an entomologist,
not for a developer, so two rules come before anything else.

1. **No dependencies.** Standard library Python only, on any machine with 3.9 or
   newer. Pillow and exiftool are optional preview helpers and every code path
   must still work when both are absent. Do not add a framework, a bundler or a
   package to make something a little nicer.
2. **Never lose or invent a record.** Scans are idempotent, determinations
   survive a renamed file through the fingerprint, and anything uncertain is
   labelled rather than filled in. A missing position stays empty. A date that
   came from the filesystem instead of the EXIF is marked `file-mtime` and shown
   in amber.

## Shape

`cli.py` is the only entry point. `scan.py` writes photo rows and clusters them
into specimen events (150 s and 60 m). `server.py` is a `ThreadingHTTPServer`
that serves `web/app.html` plus a small JSON API, binds 127.0.0.1 and requires a
per-run token. `export.py` renders the table. State is one SQLite file beside the
photographs.

The UI is a single HTML file with no build step. It reads the app through
`importlib.resources`, so the zipapp built by `build.sh` works too. If you move
that file, keep both paths working.

Determinations are stored per photo even when applied to a whole event, so
ungrouping later never loses anything.

## Before claiming it works

`python3 -m unittest discover -s tests` covers EXIF parsing, hemisphere signs,
grouping, moved files, saving and every export format. The tests build their own
JPEGs, so they need no camera and no Pillow.

The interface needs a real browser: `bd inspect "http://127.0.0.1:8731/?t=TOKEN"`
after starting a server with `ENTOLOG_TOKEN` set. Console errors there do not
show up in the Python tests.
