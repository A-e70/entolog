# entolog

Turn a folder of insect photographs into a species record table.

The photograph already knows **when** and **where**. You only know **what**. So
entolog reads the date and the position out of the EXIF, puts the picture in
front of you, and takes the four things only you can supply: species, stage,
sex, comments. Out comes the table.

```
filename,date,time,latitude,longitude,species,stage,sex,comments
IMG_0421.jpg,2026-06-14,09:26:07,51.753792,-1.257281,Vespa crabro,adult,female,"on ivy, sunny bank"
```

## Getting started

```bash
python3 -m entolog ~/photos/june-fieldwork     # reads the folder, opens the window
```

That is the whole thing. It scans, then opens a page in your browser at
`127.0.0.1`. Nothing is uploaded and nothing leaves the machine.

Or one step at a time:

```bash
python3 -m entolog scan ~/photos/june-fieldwork   # read the files
python3 -m entolog annotate                       # determine them
python3 -m entolog export -f csv -o records.csv   # write the table
```

### Installing

Nothing to install. It is standard library Python 3.9 or newer, no packages.

If you would rather have one file to copy onto a field laptop, run `./build.sh`
and take `dist/entolog.pyz`:

```bash
python3 entolog.pyz ~/photos/june-fieldwork
```

Pillow is optional and only used to preview raw files (NEF, CR2, DNG) that a
browser cannot display by itself. `exiftool` is also optional, and is used as a
second opinion on HEIC and on raws with unusual EXIF.

## The determination window

Left is the folder, grouped into **specimen events**. Consecutive shots taken
within 150 seconds and 60 metres of each other are almost always the same
individual, so they are grouped and you determine them once. `whole event` at
the bottom right is on by default; turn it off for a photograph that caught
something different.

Middle is the photograph. Scroll to zoom, drag to pan, double click for 3x. Worth
it when the difference is a tarsal segment.

Right is the record. Everything saves as you type. There is no save button and
closing the laptop loses nothing.

| key | does |
|---|---|
| `J` `K` | next photo, previous photo |
| `Enter` | save and jump to the next undetermined one |
| `D` | repeat the last determination, for a run of the same species |
| `1`...`9` | stage |
| `S` | cycle sex |
| `G` | whole event on or off |
| `F` | flag for a second look |
| `/` | jump to the species box |
| `E` | export |

Species autocompletes from what you have already typed, most used first. To
work against a checklist instead, one name per line:

```bash
python3 -m entolog species my-county-list.txt
```

## Exports

| format | for |
|---|---|
| `csv` | the plain table, the columns above |
| `full` | adds altitude, camera, lens, confidence, event number |
| `dwc` | Darwin Core, the terms GBIF, iRecord and NBN Atlas expect |
| `geojson` | drop straight onto a map |
| `md` | markdown table to paste into notes |
| `json` | everything |

```bash
python3 -m entolog export -f dwc -o occurrences.csv
python3 -m entolog set recorded_by "A Naturalist"    # fills recordedBy and identifiedBy
```

By default only determined photographs are exported. `--all` includes the rest.

## What it does about the awkward cases

**No GPS in the file.** Plenty of cameras have no receiver. The position columns
are left empty rather than guessed, and the `no position` filter lists exactly
which photographs need a grid reference adding by hand.

**No EXIF date.** Falls back to the file's own timestamp, records that it did so
in the `date_source` column, and shows it in amber in the window, so a record
that rests on a weaker date is never silently mixed in with the rest.

**Raw files.** NEF, CR2, CR3, ARW, RAF, ORF, RW2, DNG and friends are read
directly, since they are TIFF underneath. The preview uses Pillow or the JPEG the
camera already embedded in the file.

**Renamed or moved photographs.** Files are fingerprinted, so a photograph that
moves folder or gets renamed carries its determination with it on the next scan.

**Re-scanning.** Always safe. New files are added, everything already determined
is left alone.

**Southern and western hemispheres.** EXIF stores degrees and a separate N/S/E/W
reference. Both are read, so Australia and Chile come out negative rather than
mirrored, which is the classic way a record ends up in the wrong ocean.

## Files

```
entolog/exifread.py   EXIF out of JPEG, TIFF raws, PNG, WebP. No dependencies.
entolog/scan.py       folder to database, fingerprints, specimen events
entolog/db.py         SQLite schema
entolog/server.py     the local server, standard library only
entolog/web/app.html  the whole interface, one file
entolog/export.py     csv, Darwin Core, GeoJSON, JSON, markdown
tests/                22 tests, no network, no camera needed
```

Everything lives in one SQLite file next to the photographs, `entolog.db`. It is
the record, so back it up with them.

```bash
python3 -m unittest discover -s tests      # run the tests
python3 tools/make_demo.py demo-photos     # 25 fake photos with real EXIF to try
```
