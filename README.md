# entolog

Turn a folder of photographs into a species record table, with the fields you
decide on.

The photograph already knows **when** and **where**. You know **what**. So
entolog reads the date and the position out of the EXIF, works out a grid
reference, puts the picture in front of you, and takes the rest from you as fast
as you can type it.

```
filename	date	time	latitude	longitude	species	stage	sex	comments
IMG_0421.jpg	2026-06-14	09:26:07	51.753792	-1.257281	Vespa crabro	adult	female	on ivy, sunny bank
```

## Getting started

```bash
python3 -m entolog ~/photos/june-fieldwork     # reads the folder, opens the window
```

That is the whole thing. It scans, then opens a page in your browser at
`127.0.0.1`. Nothing is uploaded and nothing leaves the machine.

One step at a time:

```bash
python3 -m entolog scan ~/photos/june-fieldwork   # read the files
python3 -m entolog annotate                       # record them
python3 -m entolog export -f tsv -o records.tsv   # write the table
```

Nothing to install: standard library Python 3.9 or newer, no packages. For one
file to copy onto a field laptop, run `./build.sh` and take `dist/entolog.pyz`.

Pillow is optional and only used to preview raw files (NEF, CR2, DNG) a browser
cannot display. `exiftool` is optional too, as a second opinion on HEIC and on
raws with unusual EXIF.

## The fields are yours

A **profile** says what a record contains. Everything is generated from it: the
storage, the form in the window, the keyboard shortcuts, the autocomplete, the
validation and the export columns. Adding a field is editing a JSON file.

```bash
python3 -m entolog profile list         # insects, wildlife, plants
python3 -m entolog profile show > mine.json
python3 -m entolog profile use mine.json
```

```json
{
  "name": "moths",
  "title": "Light trap catch",
  "primary": "taxon",
  "fields": [
    {"name": "taxon", "type": "text", "learn": true, "dwc": "scientificName"},
    {"name": "count", "type": "number", "min": 1, "dwc": "individualCount"},
    {"name": "trap", "type": "choice", "digits": true, "open": false,
     "choices": ["actinic", "MV", "LED", "sugar", "net"]},
    {"name": "retained", "type": "bool", "key": "r"},
    {"name": "host_plant", "type": "text", "learn": true, "key": "h",
     "dwc": "associatedTaxa"},
    {"name": "notes", "type": "multiline", "dwc": "occurrenceRemarks"}
  ],
  "export": {"columns": ["filename", "date", "gridref", "taxon", "count", "trap", "notes"]}
}
```

| in a field | means |
|---|---|
| `type` | `text`, `choice`, `number`, `bool`, `date`, `multiline` |
| `choices` | the options, for a choice field |
| `open` | `false` to refuse anything not in the list |
| `digits` | this field takes the number keys `1` to `9`. One field only |
| `key` | a letter that cycles a choice, or jumps to a text field |
| `learn` | remember what gets typed here and offer it back, most used first |
| `required`, `min`, `max` | checks, reported without ever discarding what was typed |
| `dwc` | the Darwin Core term this field exports as |
| `help` | one line shown under the field |

The profile is copied into the database, so a set of records always carries the
definition it was made under. Switching to a profile that would orphan a field
holding records is refused unless you pass `--force`, and even then the values
stay in the database and come back if you switch back.

Load a checklist into any field that learns:

```bash
python3 -m entolog terms species county-list.txt     # one name per line,
python3 -m entolog terms host_plant plants.txt       # or "name<TAB>note"
```

## The window

Left is the folder, grouped into **specimen events**. Consecutive shots taken
within 150 seconds and 60 metres of each other are almost always the same
individual, so they are grouped and you record them once. `whole event` is on by
default; turn it off for a photograph that caught something different.

Middle is the photograph. Scroll to zoom, drag to pan, double click for 3x.
Worth it when the difference is a tarsal segment.

Right is the record, built from your profile. Everything saves as you type.
There is no save button and closing the laptop loses nothing.

| key | does |
|---|---|
| `J` `K` | next photograph, previous |
| `Enter` | save and jump to the next one still to do |
| `D` | repeat the last record, for a run of the same species |
| `1`...`9` | whichever field has `digits` |
| your letters | whatever `key` you gave each field |
| `G` | whole event on or off |
| `F` | flag for a second look |
| `/` | jump to the primary field |
| `E` | export |

## Exports

| format | for |
|---|---|
| `tsv` | the table, tab separated |
| `csv` | the same columns, commas |
| `full` | every column entolog holds, including locality and grid reference |
| `dwc` | Darwin Core, the terms GBIF, iRecord and NBN Atlas expect |
| `geojson` | drop straight onto a map |
| `md` | markdown table to paste into notes |
| `json` | everything |

```bash
python3 -m entolog export -f dwc -o occurrences.csv
python3 -m entolog set recorded_by "A Naturalist"    # fills recordedBy and identifiedBy
```

Only recorded photographs are exported. `--all` includes the rest. Every field
with a `dwc` term appears in the Darwin Core export automatically, so your own
fields travel with the record.

## Locality and grid reference

A satnav lookup gives back the whole postal hierarchy. A record wants the site
and the county:

```
Wytham Woods, Wytham, Vale of White Horse, Oxfordshire, England, OX2 8QQ, United Kingdom
                              becomes
Wytham Woods, Oxfordshire
```

Grid references are calculated from the position, offline, and are exact against
the Ordnance Survey test point (TG 51409 13177). Outside Britain the column is
simply empty.

## What it does about the awkward cases

**No GPS in the file.** The position columns are left empty rather than guessed,
and the `no position` filter lists exactly which photographs need a grid
reference adding by hand.

**No EXIF date.** Falls back to the file's own timestamp, records that it did so
in the `date_source` column, and shows it in amber in the window, so a record
resting on a weaker date is never silently mixed in with the rest.

**Raw files.** NEF, CR2, CR3, ARW, RAF, ORF, RW2, DNG and friends are read
directly, since they are TIFF underneath.

**Renamed or moved photographs.** Files are fingerprinted, so a photograph that
moves folder or gets renamed carries its whole record with it on the next scan.

**Re-scanning.** Always safe. New files are added, everything already recorded is
left alone.

**Southern and western hemispheres.** EXIF stores degrees and a separate N/S/E/W
reference. Both are read, so Australia and Chile come out negative rather than
mirrored, which is the classic way a record ends up in the wrong ocean.

**A value that fails its own rule** is still stored. Losing what someone typed is
worse than storing something odd, so the window shows the complaint and keeps the
text.

## Files

```
entolog/profile.py    what a record contains, and validating that
entolog/profiles/     the built-in profiles
entolog/records.py    reading and writing the recorder's own fields
entolog/exifread.py   EXIF out of JPEG, TIFF raws, PNG, WebP. No dependencies
entolog/locality.py   short locality from a verbose lookup, OSGB grid references
entolog/scan.py       folder to database, fingerprints, specimen events
entolog/db.py         SQLite schema and migration
entolog/server.py     the local server, standard library only
entolog/web/app.html  the whole interface, one file, built from the profile
entolog/export.py     tsv, csv, Darwin Core, GeoJSON, JSON, markdown
tests/                48 tests, no network, no camera needed
```

Everything lives in one SQLite file next to the photographs, `entolog.db`. It is
the record, so back it up with them.

```bash
python3 -m unittest discover -s tests      # run the tests
python3 tools/make_demo.py demo-photos     # 25 fake photos with real EXIF to try
```
