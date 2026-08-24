# entolog

Turn a folder of photographs into a species record table, with the fields you
decide on, from the window, the terminal or the image viewer you already use.

The photograph already knows **when** and **where**. You know **what**. So
entolog reads the date and the position out of the EXIF, works out a grid
reference, puts the picture in front of you, and takes the rest as fast as you
can type it.

```
filename	date	time	latitude	longitude	locality	species	stage	sex	comments
IMG_0421.jpg	2026-06-14	09:26:07	51.753792	-1.257281	Wytham Woods, Oxfordshire	Vespa crabro	adult	female	on ivy, sunny bank
```

Standard library Python, no packages, nothing uploaded, nothing leaves the
machine.

## Three ways in, one record

```bash
python3 -m entolog ~/photos/june        # scan the folder, open the window
python3 -m entolog enter                # or record from the keyboard, no window
python3 -m entolog edit                 # or edit the whole table in vim
```

They are the same records. The same profile, the same validation, the same
storage, the same exports. Use whichever suits the hour, and keep using your own
image viewer alongside any of them.

## Install

Nothing to install. Python 3.9 or newer.

```bash
git clone https://github.com/A-e70/entolog && cd entolog
python3 -m entolog --help
```

Or take the single file from the
[latest release](https://github.com/A-e70/entolog/releases/latest) and copy it
onto a field laptop:

```bash
python3 entolog.pyz ~/photos/june
```

Pillow is optional, only to preview raw files a browser cannot show. `exiftool`
is optional, as a second opinion on HEIC and unusual raws.

## The fields are yours

A **profile** says what a record contains. Everything is generated from it: the
storage, the form in the window, the terminal grammar, the keyboard shortcuts,
the autocomplete, the validation and the export columns. Adding a field is
editing a JSON file.

```bash
python3 -m entolog profile list          # insects, wildlife, plants
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
  "entry": {"order": ["taxon", "count", "trap", "notes", "retained", "host_plant"]},
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

`entry.order` is the order fields are typed in the terminal, which does not have
to be the order the window shows them in.

The profile is copied into the database, so a set of records always carries the
definition it was made under. Switching to a profile that would orphan a field
holding records is refused unless you pass `--force`, and even then the values
stay and come back if you switch back.

Load a checklist into any field that learns:

```bash
python3 -m entolog terms species county-list.txt     # one name per line,
python3 -m entolog terms host_plant plants.txt       # or "name<TAB>note"
```

## The window

Left is the folder, grouped into **specimen events**: consecutive shots within
150 seconds and 60 metres are almost always the same individual, so they are
grouped and you record them once. Middle is the photograph, scroll to zoom, drag
to pan, double click for 3x. Right is the record, built from your profile, saved
as you type. There is no save button and closing the laptop loses nothing.

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

## The terminal

```
$ python3 -m entolog enter

12/240 IMG_0421.jpg  2026-06-14 09:26  Wytham Woods SP4594 0830  |   [event 4, 3 shots]
> Vespa crabro / adult / f / on ivy
saved 3 photographs: Vespa crabro adult female on ivy
```

One line records a whole burst and moves to the next one still to do. Three ways
to say the same thing:

```
Vespa crabro / adult / f / on ivy      fields in order, / between them
species='Vespa crabro' sex=f           name=value, any order, any subset
vecr                                   an abbreviation, if it can only mean one thing
```

An abbreviation only resolves when it can mean exactly one thing. If it is
ambiguous you get the candidates and nothing is written. A name typed out in
full is never rewritten. Tab completes, and readline gives you history.

| | |
|---|---|
| `.` | repeat the last record |
| `-` | clear this photograph |
| `#` | flag |
| `*` | whole event on or off |
| `<` `>` | previous, next |
| `+` | jump to what your viewer is showing |
| `:n 12` | go to number 12 |
| `:f todo` | filter: todo, all, done, flagged, nogps |
| `:s` `:l` `:w` | show this record, list the table, write the table |
| `:h` `:q` | help, quit |

Commands are `:` prefixed or punctuation, so nothing you can type as a species
name is ever mistaken for one.

## Your own image viewer

Three commands, and your viewer keeps doing the looking. See
[docs/viewers.md](docs/viewers.md) for feh, nsxiv, geeqie and anything else.

```bash
export ENTOLOG_DB=~/photos/june/entolog.db
entolog current  IMG_0421.jpg                     # this is what I am looking at
entolog line     IMG_0421.jpg                     # one line for a status bar
entolog record   - "Vespa crabro / adult / f"     # record the current one
```

Once something is calling `entolog current`, the terminal follows it with
`entolog enter --follow`, and the window follows it with the **follow viewer**
button.

The status line format is yours, with every profile field available by name:

```bash
entolog line --format '{filename} {gridref} | {species} {stage}'
entolog set status_format '{filename}  {gridref}  | {record}'
```

## The table, in vim

```bash
python3 -m entolog edit          # $EDITOR on the whole table, read back on exit
python3 -m entolog table -o out.tsv
python3 -m entolog apply out.tsv
```

Columns are matched by name, so delete columns, reorder them, sort the rows, or
cut it down to `id` and one field. Deleting a row does not delete the record.
Anything failing a check is reported by line number and still kept.

## Exports

| format | for |
|---|---|
| `tsv` | the table, tab separated |
| `csv` | the same columns, commas |
| `full` | every column, including locality and grid reference |
| `dwc` | Darwin Core, the terms GBIF, iRecord and NBN Atlas expect |
| `geojson` | drop straight onto a map |
| `md` | markdown table |
| `json` | everything |

```bash
python3 -m entolog export -f dwc -o occurrences.csv
python3 -m entolog set recorded_by "A Naturalist"
```

Every field with a `dwc` term appears in the Darwin Core export automatically, so
your own fields travel with the record.

## Locality and grid reference

A satnav lookup gives back the whole postal hierarchy. A record wants the site
and the county.

```
Wytham Woods, Wytham, Vale of White Horse, Oxfordshire, England, OX2 8QQ, United Kingdom
                              becomes
Wytham Woods, Oxfordshire
```

```bash
entolog locality import places.tsv    # "lat<TAB>lon<TAB>name" or "filename<TAB>name"
entolog locality shorten --parts 1    # change your mind, everything re-shortens
entolog locality lookup               # ask OpenStreetMap, one position a second
entolog locality list
```

`lookup` is the only part of entolog that uses the network, and it only runs when
you ask for it. Positions are rounded to about 10 metres first, so one lookup
covers a whole burst.

Grid references are calculated offline and are exact against the Ordnance Survey
test point (TG 51409 13177). Outside Britain the column is simply empty.

## What it does about the awkward cases

**No GPS in the file.** The position columns stay empty rather than guessed, and
the `no position` filter lists exactly which photographs need a grid reference
adding by hand.

**No EXIF date.** Falls back to the file's timestamp, records that it did so in
`date_source`, and shows it in amber, so a record resting on a weaker date is
never silently mixed in with the rest.

**Raw files.** NEF, CR2, CR3, ARW, RAF, ORF, RW2, DNG and friends are read
directly, since they are TIFF underneath.

**Renamed or moved photographs.** Files are fingerprinted, so a photograph that
moves folder carries its whole record with it on the next scan.

**Re-scanning.** Always safe. New files are added, everything already recorded is
left alone.

**Southern and western hemispheres.** EXIF stores degrees and a separate N/S/E/W
reference. Both are read, so Australia and Chile come out negative rather than
mirrored, which is the classic way a record ends up in the wrong ocean.

**A value that fails its own rule** is still stored. Losing what someone typed is
worse than storing something odd, so the complaint is shown and the text kept.

## Files

```
entolog/profile.py    what a record contains, and validating that
entolog/profiles/     the built-in profiles
entolog/records.py    reading and writing the recorder's own fields
entolog/entry.py      the terminal loop, the status line, the viewer hooks
entolog/tsvedit.py    the table as a file you can edit and read back
entolog/exifread.py   EXIF out of JPEG, TIFF raws, PNG, WebP. No dependencies
entolog/locality.py   short locality from a verbose lookup, OSGB grid references
entolog/scan.py       folder to database, fingerprints, specimen events
entolog/db.py         SQLite schema and migration
entolog/server.py     the local server, standard library only
entolog/web/app.html  the whole window, one file, built from the profile
entolog/export.py     tsv, csv, Darwin Core, GeoJSON, JSON, markdown
tests/                123 tests, no network, no camera needed
```

Everything lives in one SQLite file next to the photographs, `entolog.db`. It is
the record, so back it up with them.

```bash
python3 -m unittest discover -s tests      # run the tests
python3 tools/make_demo.py demo-photos     # 25 fake photographs with real EXIF
./build.sh                                 # dist/entolog.pyz, one file
```

## Licence

MIT. See [LICENSE](LICENSE).
