# entolog for organisations

For recording schemes, local environmental records centres, museum and university
digitisation projects, and national data centres.

entolog turns a recorder's folder of photographs into a clean record table on
their own machine. It sits **upstream** of the systems you already run. It does
not receive records, verify them, host them or replace anything: it produces the
file you already accept, with fewer of the problems you would otherwise send
back.

Everything below is in the public repository. Nothing here is a separate edition.

## Deployment

- **One file.** `entolog.pyz` is about 200 KB and runs on any machine with Python
  3.9 or newer. It can also be installed as a normal Python package.
- **No dependencies**, no installer, no administrator rights, no service to run.
  A recorder can keep it in their home folder or on a memory stick.
- **Linux, macOS and Windows**, each covered by continuous integration on every
  change.
- **No accounts, no server, no sign-in.** The window is a local page served on
  `127.0.0.1` behind a token generated for that session.
- **Offline.** A field laptop with no connection loses no function.

Distributing it to your recorders is a matter of pointing them at the release, or
mirroring the file yourself. Either is fine under the MIT licence.

## A profile for your scheme

A profile is a JSON file listing the fields a record has. entolog generates its
storage, its form, its keyboard shortcuts, its validation and its export columns
from that file, so a profile is the whole of what a record contains.

For an organisation this means you can define, once, exactly what you want back:

- the fields, in the order that suits the recorder
- closed vocabularies where a free text answer would be a nuisance to clean, for
  example a stage or an abundance scale that will only ever take listed values
- which field is required, and which numbers have sensible bounds
- the Darwin Core term each field exports as, so your own naming does not have to
  match anyone else's
- a checklist loaded into a field, after which anything recorded off the list is
  reported before the records are sent

Hand that file to your recorders alongside the program and the records arrive in
the shape your database expects. See
[profiles.md](profiles.md) for the full reference.

## Names and identifiers

entolog ships no taxonomy. A scheme can hand its recorders the list it wants used
along with the profile, and from then on every record carries that list's
identifier, which for the UK Species Inventory is the Taxon Version Key. Names
the list does not have, and records filed under a synonym, are reported to the
recorder before anything is sent. entolog never rewrites a name.

## Sensitive records

Any record can be published as the square it falls in rather than the point:
100 m, 1 km, 2 km, 10 km or 100 km, the resolutions the atlases support. A whole
dataset can be set to a default. The exported position is the centre of the
square the reference names, with `coordinateUncertaintyInMeters` and
`informationWithheld` to match, and iRecord's `Sensitivity precision` filled in.
The exact position stays in the recorder's own database.

This also covers the ordinary case that has nothing to do with rare species: a
photograph taken in someone's garden carries their home address in its EXIF.

## Data licensing

The archive export carries a licence, and entolog accepts only the three that
GBIF will register a dataset under: CC0, CC-BY and CC-BY-NC. The recorder sets it
deliberately rather than inheriting a default.

This matters for records centres in particular. A non-commercial licence stops
some of the work a records centre is asked to do, so the choice is put in front
of the person making the records instead of being buried.

Each record carries an `occurrenceID` of the form
`urn:entolog:<dataset>:<photograph>`, built from an identifier generated once per
database and a fingerprint of the photograph. It is stable across re-exports and
distinct between recorders, so the same record reaching you by two routes is
still recognisably one record.

## Where the data lives

- Records are held in one SQLite file next to the photographs. There is no other
  copy and no cloud component.
- **Nothing is uploaded.** The single exception is `entolog locality lookup`,
  which asks OpenStreetMap what is at a position. It is a separate command that
  has to be run on purpose, and positions are rounded to about ten metres first.
- Photographs are never modified, moved or copied. entolog stores a path and a
  fingerprint.
- No telemetry, no analytics, no update check.

For an organisation this means the sensitive part, a recorder's unpublished
records and their home location in the EXIF, stays with the recorder until they
choose to send it.

## What comes out

| format | for |
|---|---|
| Darwin Core Archive | `occurrence.csv`, a `meta.xml` describing every column as a term, and an `eml.xml` with the recorder and the licence. What an IPT, GBIF and the atlases ingest |
| iRecord | the column labels iRecord's spreadsheet import offers, matched to the profile's fields by Darwin Core term |
| TSV and CSV | the profile's columns, for a scheme that wants a spreadsheet |
| GeoJSON | for a map or a GIS |
| JSON | for a pipeline of your own |

`tools/check_archive.py` in the repository validates an archive before it is
sent, and is run in continuous integration against a freshly built copy.

## Checking before records reach you

`entolog check` runs the obvious part of a verifier's job on the recorder's own
machine, while the photographs are still in front of them: a record with no
position, a camera clock set to the future or reset to 1980, one name written two
ways, two names a letter apart, a name that is not on the checklist you supplied,
a required field left empty, a value outside its own vocabulary.

These are the corrections that otherwise take an exchange of emails weeks later.

## Support and integration

entolog is free software and will stay that way. What an organisation might
reasonably want beyond it:

- a profile written for your scheme, and a checklist loaded into it
- an export preset matching the exact import format your database takes, in the
  way the iRecord preset already does
- help getting it in front of your recorders: a short guide in your own words,
  or a mirrored download
- adapting it where your workflow differs from the assumptions here, for example
  a different grid reference system or a field type that does not exist yet
- maintenance and a route for reporting problems

That work is a conversation rather than a price list, and it is currently one
developer. The honest position today is that **entolog is looking for
organisations willing to try it with a real dataset**, and what would be most
useful is a recorder's actual card of photographs and an opinion on whether it
saved them anything.

## What entolog does not do

- **No identification.** There is no image recognition and no suggested names.
- **No taxonomy.** Names are not matched against the UK Species Inventory, the
  GBIF backbone or anything else, and no taxon version keys are produced. It
  remembers what the recorder types and reports when they have typed it two ways.
- **No verification workflow.** No reviewers, no statuses, no comments.
- **No image recognition**, and no taxonomy of its own.
- **No hosting, no sharing, no multi-user access.** One recorder, one folder.
- **Not a photo manager.** It never writes to an image file.

If you need any of those, entolog is the step before them, not a replacement.

## Evaluating it

```bash
curl -LO https://github.com/A-e70/entolog/releases/latest/download/entolog.pyz
python3 entolog.pyz demo
```

That writes a folder of demo photographs with real EXIF, reads them and opens the
window. Nothing is installed and nothing is uploaded.

- Source: [github.com/A-e70/entolog](https://github.com/A-e70/entolog)
- 273 tests, run with `python3 -m unittest discover -s tests`, no network needed
- Continuous integration across Python 3.9 to 3.14 on Linux, macOS and Windows
- MIT licensed, and every published version stays that way

Questions, or an offer of a dataset to test against, are best raised as an issue
on the repository, which also reaches the author by email.
