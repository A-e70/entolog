# Changelog

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
