# Getting records out

Only recorded photographs are exported. `--all` includes the rest.

```bash
entolog export -f tsv -o records.tsv
entolog export -f dwca -o records.zip
entolog export -f irecord -o for-irecord.csv
```

## Which one

| you are sending to | use |
|---|---|
| GBIF, an IPT, the NBN Atlas, most national atlases | `dwca` |
| iRecord | `irecord` |
| a county recorder or a scheme organiser who wants a spreadsheet | `tsv` or `csv` |
| NBN Record Cleaner | `csv` |
| yourself, in QGIS or on a map | `geojson` |
| a script | `json` |
| a note or an email | `md` |

## dwca, a Darwin Core Archive

A zip holding three files, which is what GBIF and the atlases actually ingest:

```
occurrence.csv   one row per record, columns named as Darwin Core terms
meta.xml         says which column is which term, so nothing has to be guessed
eml.xml          who made the dataset, what it covers, and the licence
```

Set these first. They end up in `eml.xml` and in every record:

```bash
entolog set recorded_by "A Naturalist"
entolog set licence CC-BY          # CC0, CC-BY or CC-BY-NC only
entolog set dataset_title "Wytham Woods aculeates 2026"
entolog set contact_email "you@example.org"
entolog set abstract "Records made from photographs during..."
entolog set                        # show what is set
```

GBIF will not register a dataset unless the licence is CC0, CC-BY or CC-BY-NC.
CC-BY-NC also stops some local environmental record centres using the records
at all, so pick it knowingly rather than by default.

Every record carries an `occurrenceID` like
`urn:entolog:6b1e...:b0b5e7af058d68de`, built from a dataset identifier made once
for this database and a fingerprint of the photograph. It is stable across
re-exports and unique between databases, which is what stops the same record
being counted twice when it reaches an aggregator by two routes.

The archive includes every field in your profile that has a `dwc` term, so your
own fields travel with the records rather than being flattened away.

## irecord

The columns iRecord's spreadsheet import offers, so the mapping step maps itself:

```
Species or taxon name, Date, Spatial reference, Location name, Recorder Name,
Identified By, Quantity, Stage, Sex, Occurrence comment, Recorder certainty
```

Dates are written `dd/mm/yyyy`. The spatial reference is the OSGB grid reference
when there is one, and decimal latitude and longitude otherwise.

Your fields are matched to these columns by their Darwin Core term, not by name,
so a profile whose primary field is called `taxon` still fills in "Species or
taxon name".

## tsv and csv

The columns your profile lists in `export.columns`, in that order. `--columns`
overrides:

```bash
entolog export -f tsv --columns filename,date,gridref,species,count
```

`full` gives every column entolog holds, including locality, grid reference,
altitude, camera, lens, specimen event number and where the date came from.

## The editable table

`tsv` writes a table for reading. `entolog table` writes one for **editing**, with
an `id` column so it can be read back:

```bash
entolog table -o june.tsv
vim june.tsv
entolog apply june.tsv
```

or in one step, `entolog edit`. See [the vim section of the README](../README.md#the-table-in-vim).

## geojson

One point per record, with the profile's fields as properties. Records with no
position are left out rather than placed at zero, which is where a null island
comes from.

## What is never exported

The photographs themselves. entolog stores a path and a fingerprint, never a
copy, and never writes to your image files.
