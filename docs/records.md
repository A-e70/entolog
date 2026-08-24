# Getting a record right

A record is only as good as its name, its date and its position. entolog can
check all three against something better than your memory, and put back anything
it gets wrong.

> `entolog` here means whichever way you installed it: the command,
> `python3 entolog.pyz`, or `python3 -m entolog` from a clone.

## Names: bring your own taxonomy

entolog ships no taxon list. The UK Species Inventory, a GBIF backbone extract
and a scheme's own checklist all have their own terms of use, so you bring the
one you are entitled to and entolog reads whatever columns it has.

```bash
entolog taxa import uksi.csv
entolog taxa show
```

It recognises the usual column headings on its own, and tells you which it
matched:

```
2143 names loaded, 318 of them synonyms
columns read: name from 'Recommended name', authority from 'Authority',
rank from 'Rank', taxon_id from 'Recommended Taxon Version Key',
accepted from 'Accepted name', vernacular from 'Common name'
```

If it misses one, point at it:

```bash
entolog taxa import list.csv --map name=Taxon,taxon_id=TVK
```

Once a list is loaded:

- **Suggestions come from it**, with the authority or the common name beside each
  entry, so typing `hornet` finds *Vespa crabro*.
- **Synonyms say what they are.** Typing `ina` offers *Inachis io*, marked
  *synonym of Aglais io*. You may still record it: nothing is rewritten.
- **The identifier travels.** Every export carries `taxonID`, which for the UK
  Species Inventory is the Taxon Version Key, plus
  `scientificNameAuthorship`, `taxonRank` and `acceptedNameUsage`. The iRecord
  export gains a Taxon Version Key column, which is the most reliable way for its
  import to match a name.
- **`entolog check` reports** any name the list does not have, and any record
  filed under a synonym.

Without a list, everything still works. You simply do the matching by hand
later, or the scheme does.

## Dates: the camera clock

A clock that was never set, or that reset itself when the battery went flat, is
the commonest fault in a set of photographic records.

```bash
entolog time
```

```
   20  exif
    1  file-mtime

20 photographs carry a satellite fix as well as a camera time.
  the camera reads +1h47m against UTC
  in a +1h zone the clock is 47m fast
  in a +2h zone the clock is 13m slow

Correct it with the zone you were in:
  entolog time --from-gps --zone +1h
```

Where the camera recorded a GPS fix it also recorded the satellite time, which is
correct by definition. The difference between that and the camera is a whole time
zone plus whatever the clock is out by, and **nothing in the file says which is
which**, so entolog offers both readings rather than picking one and being
quietly wrong.

Other ways in, when there is no satellite time:

```bash
entolog time --set "IMG_0001.jpg=2026-06-14 09:26"   # everything moves with it
entolog time --shift +3h12m
```

Nothing is written to your photographs. Corrected dates are marked
`exif+corrected` in the `date_source` column so a shifted date is never mistaken
for one straight off the camera, specimen events are regrouped afterwards, and
the same command with the opposite sign puts it back.

## Positions: which grid, and how precise

Grid references are calculated offline from the position in the photograph.
Britain gets the Ordnance Survey grid, Ireland gets the Irish grid, and entolog
works out which by where the photograph was taken. Anywhere else the column is
empty rather than wrong, and the decimal position is used instead.

```bash
entolog set grid irish     # or osgb, or auto, which is the default
```

### Publishing a square instead of a point

The EXIF position of a photograph taken in your own garden is your home address.
A record of a sensitive species is a map to it. Both are reasons to publish the
square rather than the point.

```bash
entolog record IMG_0421.jpg --precision 1km   # this record only
entolog set blur 1km                          # everything, unless a record says otherwise
```

In the window there is a **publish as** control under each record; in the
terminal it is `:p 1km`. The choices are the ones the atlases support: `100m`,
`1km`, `2km`, `10km`, `100km`.

A blurred record exports as:

- the grid reference cut down to that square, written as a tetrad for 2 km
- a latitude and longitude at **the centre of that same square**, so the two can
  never disagree
- `coordinateUncertaintyInMeters` set to the distance from the centre to a corner
- `informationWithheld` saying what was done
- iRecord's `Sensitivity precision` in metres

The exact position stays in your own database. Only the export is coarsened.

## More than one thing in one photograph

A photograph usually holds one record and behaves exactly as it always has. When
it holds more, each one is numbered.

```
> Noctua pronuba / 12
saved 3 photographs: Noctua pronuba 12
> :o +
record 2 on this photograph. Type what it is, or move on and nothing is kept.
> Xestia c-nigrum / 2
saved 3 photographs (record 2): Xestia c-nigrum 2
> :o
 > 1  Noctua pronuba 12
   2  Xestia c-nigrum 2
   :o 2 to switch, :o + for another, :o - to remove one
```

In the window, **+ record** does the same and a row of tabs appears at the top of
the form.

Each record exports as its own occurrence with its own identifier. The first
record on a photograph keeps the identifier it always had, so re-exporting after
adding a second one does not disturb the first. An empty record is never written
and never exported.

## Taking it back

```bash
entolog undo            # the last change
entolog undo --list     # what that would put back, without doing it
entolog undo -n 5
```

One keystroke that records a whole specimen event is one step back. An edited
table read in with `entolog apply` is one step back. In the window it is
`Ctrl+Z`, in the terminal `:u`.

## Keeping it

The database next to your photographs is the record. Nothing else holds it.

```bash
entolog backup                       # entolog-backup.db beside the original
entolog backup ~/Dropbox/june.db
```
