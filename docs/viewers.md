# Using entolog with the image viewer you already have

entolog does not want to replace your viewer. Every workflow writes to the same
database, through the same profile and the same validation, so you can use the
window, the terminal, your own viewer, or all three in the same session.

> **`entolog` below means whichever way you installed it.** If you are running
> the single file, either move it onto your path as `entolog`, or write
> `python3 /path/to/entolog.pyz` in these examples.

Three commands are all the integration there is.

```bash
entolog current  <file>            # this is what I am looking at now
entolog line     [file]            # one line about it, for a status bar
entolog record   <file|-> "<line>" # record it, - means the current one
```

Point them at a database once and forget about it:

```bash
export ENTOLOG_DB=~/photos/june/entolog.db
```

## A status line

`entolog line` prints one line. The format is yours, and every field in your
profile is available by name, along with the things the photograph knows.

```bash
$ entolog line IMG_0421.jpg
IMG_0421.jpg  2026-06-14 09:26:07  Wytham Woods, Oxfordshire SP4594 0830  | Vespa crabro adult female

$ entolog line IMG_0421.jpg --format '{filename} {gridref} | {species} {stage}'
IMG_0421.jpg SP45940830 | Vespa crabro adult
```

Available everywhere: `{index} {filename} {path} {date} {time} {datetime}
{locality} {gridref} {where} {lat} {lon} {position} {event} {camera} {record}
{flag}`, plus one for every field in your profile.

Set a default so you do not have to pass it every time:

```bash
entolog set status_format '{filename}  {gridref}  | {record}'
```

## feh

```bash
feh --action1 "entolog record %f 'Vespa crabro / adult'" \
    --action2 "entolog current %f" \
    --info "entolog line %f" \
    ~/photos/june/*.jpg
```

`--info` runs the command for each image and shows the output at the bottom of
the window, which is exactly the status line. `1` records, `2` tells entolog what
you are looking at so a terminal running `entolog enter --follow` jumps to it.

## nsxiv or sxiv

nsxiv pipes the marked or current file to a key handler script. Put this in
`~/.config/nsxiv/exec/key-handler`, `chmod +x` it, and press `Ctrl-x` then the
key.

```sh
#!/bin/sh
export ENTOLOG_DB=~/photos/june/entolog.db
while read -r file; do
  case "$1" in
    c) entolog current "$file" ;;
    r) entolog record "$file" "$(printf '' | dmenu -p 'record:')" ;;
    f) entolog record "$file" --flag ;;
  esac
done
```

## geeqie

Geeqie has user commands in Edit, Preferences, Plugins. Add one with the command
`entolog current %f` and give it a keyboard shortcut. Anything Geeqie shows you
then becomes what entolog is pointed at.

## Anything else

If your viewer can run a command with the current filename in it, it can drive
entolog. If it cannot, it can probably write the filename somewhere, and a two
line loop bridges the gap:

```bash
tail -F ~/.cache/myviewer/current | while read -r f; do entolog current "$f"; done
```

## Following, from the other side

Once something is calling `entolog current`, both other workflows can follow it.

```bash
entolog enter --follow      # the terminal jumps to whatever you are looking at
```

In the window, press the **follow viewer** button in the top bar. It checks about
once a second and selects the photograph your viewer is showing.

`+` in the terminal jumps to the current photograph once, without following.

## Recording without any viewer at all

```bash
entolog enter
```

```
12/240 IMG_0421.jpg  2026-06-14 09:26  Wytham Woods SP4594 0830  |   [event 4, 3 shots]
> Vespa crabro / adult / f / on ivy
saved 3 photographs: Vespa crabro adult female on ivy
```

One line records the whole burst and moves to the next one. `.` repeats the last
record, an abbreviation like `vecr` resolves to the only name it can mean, and
Tab completes. `:h` lists everything.

## The table, in vim

```bash
entolog edit            # opens $EDITOR on the whole table, reads it back on exit
entolog table -o out.tsv
entolog apply out.tsv
```

Columns are matched by name, so you can delete columns, reorder them, sort the
rows, or cut it down to `id` and one field. Deleting a row does not delete the
record. Anything that fails a check is reported by line number and still kept.
