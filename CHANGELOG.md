# Changelog

## 1.6.0

**The photograph viewer.** Zooming jumped, bounced and ran away too fast, and the
photograph slid out from under the pointer. Measured before the change: a point
sitting at 0.800 across the photograph had drifted to 0.912 after four notches of
the wheel. Measured after: it does not move at all, in or out, to any
magnification.

- **The anchor was being measured against a moving box.** The position came from
  `getBoundingClientRect`, which already has the zoom in it, so every step
  compounded the error. It now comes from the layout, which does not move.
- **Every wheel event was a fixed jump**, so a trackpad sending fifty small
  events zoomed fifty times as fast as a mouse sending one. Wheel deltas are now
  normalised across pixels, lines and pages, a mouse notch is about a quarter
  more, ten trackpad ticks are about a tenth more, a pinch is finer still, and
  one violent flick is still one step.
- **Zoom now eases towards where it is going** instead of snapping, so a run of
  notches glides. Dragging still follows the hand exactly, and easing is off
  where the system asks for reduced motion.
- **The photograph can no longer be dragged off its own frame.** Larger than the
  window it stops at its edges, smaller than the window it stays centred.
- **A sensible limit tied to the photograph.** Zooming stops at twice the
  photograph's own pixels rather than an arbitrary twelve, so it never becomes
  mush. Double click goes to exactly 1:1 with those pixels and back, and `0` fits
  it again.
- **The readout is a percentage** of the photograph's own pixels, so it is
  obvious when what is on screen is interpolation.

The arithmetic behind all of that now lives in one marked block of `app.html` and
is run in node by the test suite, so it is the shipped code being tested. Eleven
new tests, skipped where node is not installed.

286 tests.

## 1.5.1

**Tapping stage, sex or confidence did nothing visible.** The value was saved
correctly every time, but the button never lit up, so the window looked frozen
and there was no way to tell whether it had worked.

The cause: a clicked button becomes the focused element and carries the same
`data-field` marker a text box does, and the code that avoids redrawing the form
while someone is typing was treating that as typing. It now looks at what kind of
element has focus. A chip also lights up the moment it is pressed rather than
waiting for the write to come back, so the window answers a tap immediately.

Flagging now applies to the photograph rather than the whole specimen event,
which is what the terminal has always done and what "flag for a second look" at a
picture means.

## 1.5.0

**A photograph can hold more than one record.** A light trap egg box holds ten
moths, a leaf holds two mines, a flower holds a bumblebee and a hoverfly. Each
record on a photograph is numbered, exports as its own occurrence, and the first
one keeps the identifier it always had. **+ record** in the window, `:o +` in the
terminal, a `record` column in the editable table, and nothing is written until
something is typed, so changing your mind leaves nothing behind. A photograph
with one record behaves exactly as it did.

**The window can no longer fail silently**, which is what "it does not work
sometimes" turned out to mean. Three separate causes, all now fixed:

- The key is now a property of the record file rather than of one run, so a
  bookmark, or a tab left open while entolog is restarted, keeps working.
- A link with no key, or the wrong one, gets a page explaining what happened and
  what to do, instead of the words `bad or missing token`.
- Anything that fails now says so in the window with a way to try again. Before,
  a refused request left a blank page and no explanation.

**Two real data bugs found by testing the window rather than the code.** A field
could write into whichever photograph was selected by the time it lost focus, so
a name typed on one photograph could land on the next one. And a record applied
to a whole specimen event was written into memory after the selection had already
moved, so the window could show the wrong species against the right photograph.
Both are fixed and both were invisible to the Python tests.

Also: pressing E twice no longer throws, and `entolog annotate` flushes its link
so piping the output shows it.

273 tests.

## 1.4.0

Five things stood between entolog and a record a scheme can use without touching.

**Names carry an identifier.** entolog ships no taxonomy, because the UK Species
Inventory, a GBIF extract and a scheme's own checklist all have their own terms
of use. Bring the list you are entitled to and `entolog taxa import` reads
whatever columns it has, matching the usual headings on its own. From then on
suggestions come from it, a synonym is offered as what it is, `taxonID`,
`scientificNameAuthorship`, `taxonRank` and `acceptedNameUsage` follow every
record into the archive, the iRecord export gains a Taxon Version Key column, and
`entolog check` reports names the list does not have. Nothing typed is ever
rewritten.

**The camera clock can be measured and corrected.** `entolog time` compares the
camera against the satellite time the camera itself recorded. Which part of the
difference is a time zone is not in the file, so both readings are offered rather
than one guessed. `--from-gps --zone +1h`, `--set 'IMG_0001.jpg=...'` or
`--shift +3h12m` apply it, corrected dates are marked as corrected, specimen
events regroup, and the opposite shift puts it back.

**Positions outside Britain, and positions that should not be published.** The
Irish grid is calculated as exactly as the British one, and entolog picks the
grid by where the photograph was taken. Any record can be published as the square
it falls in instead of the point, at 100 m, 1 km, 2 km, 10 km or 100 km, with the
exported position at the centre of that same square, `coordinateUncertaintyInMeters`
and `informationWithheld` to match, and iRecord's `Sensitivity precision` filled
in. This matters for a rare species and equally for a photograph taken in your own
garden.

**Everything can be taken back.** `entolog undo`, `Ctrl+Z` in the window, `:u` in
the terminal. One keystroke that records a whole specimen event is one step back,
and so is a whole table read in from `$EDITOR`.

**The record can be copied somewhere safe.** `entolog backup`.

Also: a card of several thousand photographs draws only the tiles on screen.
Fixed a keyboard handler that used a variable before it was declared, which broke
every shortcut in the window; found in a browser, which is the only place it
could have been found.

256 tests.

## 1.3.0

**Suggestions, from your own records.** Any field that learns now offers what is
already in the dataset alongside whatever checklist was loaded, ranked so a name
you have recorded before comes first. A common name finds the scientific one, a
prefix finds the second word as well as the first, and an abbreviation finds the
only thing it can mean. The list is derived from the records themselves, so it
needs no upkeep: record a species and it is offered from then on, and it stops
being offered when the last record of it goes.

Nothing typed is ever replaced unless a suggestion is chosen. The window says so
under the list while you type, and Enter without choosing keeps exactly what was
written. The terminal uses the same list through the same code, resolves only
when one thing could have been meant, and shows the choices when more could.

**A quieter glass interface.** Translucent panels either side of the photograph,
which itself stays on near black and is never tinted. Clearer selected and
focused states: the chosen photograph lifts and glows, the record being worked on
carries an accent bar, focused fields get a ring. Selected chips use dark ink on
the bright fill, which is the difference between 2.7:1 and 4.7:1 contrast. Motion
is off when the system asks for that, and there is a flat fallback where
backdrop filters are not supported.

**Fixed:** two entolog windows open on one machine logged each other out, because
cookies are not scoped by port. The session cookie is now named for the port and
the page carries its own token. The terminal no longer reports "saved 0
photographs" after refusing an ambiguous name.

202 tests.

## 1.2.1

- Continuous integration: the suite on Python 3.9, 3.11, 3.13 and 3.14, on Linux,
  macOS and Windows, plus a job that builds `entolog.pyz`, runs the demo a
  stranger runs first, and installs the package into a clean environment
- **The profiles were missing from the installed package**, so `pip install`
  followed by `entolog demo` could not load a profile. Fixed and now checked in CI
- A line in `entolog doctor` could not be parsed by any Python before 3.12.
  Nothing in the test suite imported the command line; now everything is imported
- `rel_path` is stored with forward slashes whatever made it, so a database made
  on Windows reads the same everywhere
- Pointing entolog at a memory card or any read only folder explains itself
  instead of ending in a traceback, and the thumbnail cache falls back to a
  temporary folder
- Scanning a folder with no photographs in says so, and says what it looks for
- The documentation now says once, clearly, that `entolog` means whichever of the
  three ways you installed it

## 1.2.0

Ready for someone else to pick up.

- `entolog demo` writes 21 demo photographs with real EXIF and opens the window,
  so entolog can be evaluated with nothing installed and no camera card
- `entolog check`, a record cleaning pass: no position, a camera clock set to the
  future or reset to 1980, one name written two ways, two names one letter apart,
  a name that is not in the checklist you loaded, a required field left empty, a
  value that breaks its own rule, a burst holding two species, still flagged
- `export -f dwca` writes a real Darwin Core Archive: `occurrence.csv`,
  `meta.xml` and `eml.xml` in a zip, with the licence and the recorder in the
  metadata, and a stable `urn:entolog:` occurrenceID unique between databases
- `export -f irecord` writes the columns iRecord's spreadsheet import offers,
  matching your fields to them by Darwin Core term
- `entolog set` with no arguments lists the dataset settings and what they are
  for, and refuses a licence GBIF will not accept
- `entolog doctor` checks the machine
- `moths` and `birds` profiles added
- grid references are backfilled for databases scanned before 1.1
- documentation: quick start, profile reference, export guide, viewer
  integration, an honest comparison with iRecord, iNaturalist, MapMate and a
  spreadsheet, and a project page with screenshots

## 1.1.0

- The terminal loop, `entolog enter`: fields in profile order separated by `/`,
  or `name=value`, or a bare line. Abbreviations resolve only when unambiguous.
  Commands are `:` prefixed so nothing typeable as a species is mistaken for one
- `entolog current`, `line` and `record`, so an existing image viewer drives
  entolog, with follow mode in both the terminal and the window
- `entolog edit`, `table` and `apply`: the whole table in `$EDITOR`, columns
  matched by name, deleting a row leaves the record alone
- `entolog locality`: verbose reverse geocodes cut down to site and county,
  offline OSGB grid references
- `entry.order` in a profile
- Security: `Referrer-Policy: no-referrer` and `rel="noreferrer"` so the session
  token cannot leak through an outbound link, `HttpOnly` on the cookie, `nosniff`

## 1.0.0

- Profiles: the fields a record has are a JSON file, and everything is generated
  from it. Values live one row per field, so a new field needs no migration
- The window: filmstrip grouped into specimen events, zoomable photograph,
  keyboard-driven form, saved as you type
- EXIF read from JPEG, TIFF raws, PNG and WebP with no dependencies
- Specimen events: shots within 150 seconds and 60 metres grouped as one
- Exports: TSV, CSV, Darwin Core, GeoJSON, JSON, markdown
