# Profiles: deciding what a record contains

A profile is a JSON file listing the fields a record has. entolog generates
everything else from it: the storage, the form in the window, the grammar in the
terminal, the keyboard shortcuts, the autocomplete, the validation, the export
columns and the Darwin Core terms.

There is no field list anywhere in the code. Adding a field is editing a file.

```bash
python3 -m entolog profile list          # what comes built in
python3 -m entolog profile show > mine.json
python3 -m entolog profile use mine.json
python3 -m entolog profile check mine.json   # is it usable, without adopting it
```

## Built in

| profile | fields |
|---|---|
| `insects` | species, stage, sex, confidence, comments |
| `moths` | taxon, count, trap, worn, retained, host plant, notes |
| `wildlife` | species, count, stage, sex, behaviour, habitat, determiner, comments |
| `birds` | species, count, activity, stage, sex, habitat, notes |
| `plants` | species, abundance (DAFOR), phenology, habitat, comments |

Start from whichever is closest, `profile show > mine.json`, and edit.

## A field

```json
{"name": "trap", "type": "choice", "digits": true, "open": false,
 "choices": ["actinic", "MV", "LED", "sugar", "net"],
 "dwc": "samplingProtocol", "help": "how it was caught"}
```

| key | meaning |
|---|---|
| `name` | the column name. Letters, digits and underscore. Must not be one of the things the photograph already provides (`filename`, `date`, `latitude`, `gridref`, `locality` and so on) |
| `label` | what the window shows. Defaults to the name with underscores as spaces |
| `type` | `text`, `choice`, `number`, `bool`, `date`, `multiline` |
| `choices` | the options for a choice field. An empty string in the list means "none" |
| `open` | `false` refuses anything not in `choices`. Default `true` |
| `digits` | this field takes the number keys `1` to `9`. One field per profile, at most nine choices |
| `key` | one letter. Cycles a choice field, or jumps to a text field. `j k d g f e / ? < >` are taken |
| `learn` | remember what is typed here and offer it back, most used first |
| `required` | reported by `entolog check` when empty |
| `min`, `max` | for numbers |
| `dwc` | the Darwin Core term this field exports as. See below |
| `help` | one line under the field, and the placeholder in the box |

A field can also be written as a bare string when it needs nothing but a name:

```json
{"name": "quick", "fields": ["species", "notes"]}
```

## The profile itself

| key | meaning |
|---|---|
| `name` | short name |
| `title` | shown in the window |
| `primary` | the field that decides whether a photograph counts as recorded. Defaults to the first |
| `entry.order` | the order fields are typed in the terminal, which does not have to be the order the window shows them |
| `export.columns` | the default columns for `csv` and `tsv`. Any field name, or anything the photograph provides |

## Darwin Core terms

Any field with a `dwc` term appears in the Darwin Core and archive exports under
that term, and the iRecord export finds its columns by term as well, so your own
field names do not have to match anybody else's. Terms worth knowing:

| term | for |
|---|---|
| `scientificName` | the name. Almost always your primary field |
| `individualCount` | how many |
| `lifeStage` | adult, larva, nymph and so on |
| `sex` | male, female, worker |
| `behavior` | what it was doing |
| `habitat` | where it was |
| `occurrenceRemarks` | free comments |
| `identifiedBy`, `identificationVerificationStatus` | who determined it, and how sure |
| `associatedTaxa` | host plant, prey, what it was on |
| `samplingProtocol` | trap type, net, beating tray |

The full list is at [dwc.tdwg.org/terms](https://dwc.tdwg.org/terms/). Anything
without a `dwc` term still exports to TSV and CSV, it just does not travel into
the archive.

## Changing your mind

The profile is copied into the database, so a set of records always carries the
definition it was made under.

Adding fields is free. Removing a field that already holds records is refused:

```
$ entolog profile use wildlife
this profile drops fields that already hold records: confidence (1 record).
The values stay in the database either way, but they would stop being shown or
exported. Repeat with --force if that is what you want.
```

Even with `--force`, nothing is deleted. Switch back and the values are there.

## Checklists

Any field with `learn` can be loaded with a list:

```bash
entolog terms species county-checklist.txt
entolog terms host_plant plants.txt
```

One entry per line, or `entry<TAB>a note shown beside it`. Once a checklist is
loaded, `entolog check` reports anything recorded that is not on it, which is how
a typo in a name you have only used once gets caught.
