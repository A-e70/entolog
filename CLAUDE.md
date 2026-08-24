# entolog

Photographs to a species record table, for recorders rather than developers.
Three rules come before anything else.

1. **No dependencies.** Standard library Python only, 3.9 or newer. Pillow and
   exiftool are optional preview helpers and every path must still work when both
   are absent. Do not add a framework, a bundler or a package to make something a
   little nicer.
2. **Never lose or invent a record.** Scans are idempotent, records survive a
   renamed file through the fingerprint, a value that fails validation is stored
   anyway with the complaint shown, and switching profile never deletes values.
   Anything uncertain is labelled rather than filled in: a missing position stays
   empty, a date that came from the filesystem is marked `file-mtime` and shown
   in amber.
3. **Nothing downstream may know what the fields are.** Fields come from the
   active profile. If you find yourself writing `species` or `stage` anywhere
   outside `profiles/*.json` and the tests, it is wrong. The one exception is the
   `_flag` built-in, kept apart by a leading underscore that profiles cannot use.

## Shape

`profile.py` defines and validates what a record contains. `records.py` reads and
writes values through it. `scan.py` writes photo rows and clusters them into
specimen events (150 s, 60 m). `server.py` is a `ThreadingHTTPServer` serving
`web/app.html` plus a JSON API, bound to 127.0.0.1 behind a per-run token.
`export.py` renders the table, taking its columns and its Darwin Core terms from
the profile, and builds the Darwin Core Archive. `locality.py` shortens a verbose
reverse geocode and computes OSGB grid references offline. `entry.py` is the
terminal loop, the status line and the viewer hooks; `tsvedit.py` is the editable
table; `check.py` is the record cleaning pass; `taxonomy.py` holds the taxon list the
recorder supplies and `clock.py` measures the camera against the satellites;
`records.suggest` is the one place suggestions are ranked, used by the window and
by `entry.resolve`, so both offer the same list; `demo.py` and `demodata.py` build
the demo folder using `exifwrite.py`, the only place EXIF is ever written.

Values live in `field_values(photo_id, field, value)`, one row per field, so a
new field is data rather than a migration. The active profile is stored in `meta`
so a database is self describing. `db._carry_over` moves 1.0 records out of the
old fixed columns on first open; the old `records` table is deliberately left in
place as a safety net.

The UI is a single HTML file with no build step, and builds its form, its
keyboard shortcuts and its help from `/api/state`. It reads itself through
`importlib.resources`, so the zipapp from `build.sh` works too.

## Before claiming it works

`python3 -m unittest discover -s tests` is 256 tests: EXIF parsing, hemisphere
signs, grouping, moved files, profile validation, custom fields the code has
never seen, the 1.0 migration and every export format. They build their own
JPEGs, so no camera and no Pillow.

The window needs a real browser. Start a server with `ENTOLOG_TOKEN` set, then
`bd inspect "http://127.0.0.1:8731/?t=TOKEN"`. Console errors do not show up in
the Python tests. Test it against a profile that is **not** the default, or you
are only testing the insect fields. `bd type` refuses fields whose placeholder
looks like a credential, and "start typing" contains "pin", which is worth
remembering before blaming the page.
