# Quick start

Five minutes, from nothing to a file a recording scheme will take.

> **`entolog` here means whichever way you installed it:** the command,
> `python3 entolog.pyz`, or `python3 -m entolog` from a clone. On Windows, `py`
> rather than `python3`. See [installing](../README.md#install).

## 1. Try it without a camera card

```bash
python3 -m entolog demo
```

That writes 21 demo photographs, reads them, loads a short checklist of names,
records two specimen events so there is something to look at, and opens the
window. The pictures are drawings; the EXIF dates and positions in them are real,
so everything downstream behaves exactly as it will on your own card.

Press `J` and `K` to move, type a name, press `1` for adult, `Enter` to save and
jump to the next one still to do.

## 2. Your own photographs

```bash
python3 -m entolog ~/photos/june-fieldwork
```

It reads the folder, works out the date and position of each photograph from the
EXIF, calculates a grid reference, groups bursts into **specimen events**, and
opens the window. Nothing is uploaded. Nothing is written to your photographs.

Re-running it later is always safe: new files are added, everything already
recorded is left alone.

## 3. Record

Whichever of these suits the hour. They are the same records.

```bash
python3 -m entolog annotate     # the window
python3 -m entolog enter        # the keyboard, no window
python3 -m entolog edit         # the whole table in $EDITOR
```

In the terminal, one line records a whole burst:

```
12/240 IMG_0421.jpg  2026-06-14 09:26  Wytham Woods SP4594 0830  |   [event 4, 3 shots]
> Vespa crabro / adult / f / on ivy
saved 3 photographs: Vespa crabro adult female on ivy
```

`.` repeats the last record. `vecr` resolves to the only name it can mean. Tab
completes. `:h` lists everything.

If you load a checklist with common names beside the scientific ones, typing the
common name finds the record you want:

```bash
entolog terms species checklist.txt      # "Vespa crabro<TAB>hornet"
```

Then typing `hornet` in the window offers *Vespa crabro*. The record still keeps
the scientific name, which is what a scheme wants.

## 4. Say who you are, once

```bash
python3 -m entolog set recorded_by "A Naturalist"
python3 -m entolog set licence CC-BY
```

The licence has to be `CC0`, `CC-BY` or `CC-BY-NC`. GBIF will not register a
dataset under anything else, and a licence that forbids commercial use stops some
local record centres using your records at all, so choose deliberately.

## 5. Check before you send

```bash
python3 -m entolog check
```

```
! 3 records have no position
    Add a grid reference by hand, or use the 'no position' filter
    IMG_0455.jpg, IMG_0456.jpg, IMG_0461.jpg
? species written 2 ways: 'Vespa crabro', 'Vespa  crabro'
    Only spacing or capitals differ, so these are one name
- 4 photographs are still flagged
```

This is the pass a scheme's verifier would do, run on your own machine while the
photographs are still in front of you.

## 6. Send it

```bash
python3 -m entolog export -f dwca -o records.zip     # Darwin Core Archive
python3 -m entolog export -f irecord -o irecord.csv  # iRecord's import columns
python3 -m entolog export -f tsv -o records.tsv      # a plain table
```

See [exports.md](exports.md) for which one a given scheme wants.

## Where everything lives

One SQLite file, `entolog.db`, next to the photographs. It holds the records, the
profile they were made under, and the names you have typed. Back it up with the
photographs; it is the record.
