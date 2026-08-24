# Where entolog fits

There is a lot of good biological recording software. entolog does not replace
any of it, and it is worth being clear about what it is not.

## The gap it fills

A day in the field produces a card full of photographs. Somewhere between that
card and a recording scheme, somebody has to sit down and turn pictures into
rows: name, date, place, stage, sex, notes. In collection digitisation this
manual step has been measured at up to 90 per cent of the total effort, and for
an individual recorder it is the reason a card sits undone for a season.

Almost every tool in this space starts *after* that step, from a spreadsheet you
have already filled in, or a record you are typing into a web form one at a time.

entolog is the step itself. Photographs in, a clean table out, on your own
machine, with the fields you decided on, and then an export to whichever of the
tools below you already use.

## Compared with what people actually use

**iRecord** is where UK records go. It feeds the NBN Atlas and the national
recording schemes, and its verifiers are the reason its data is trusted. It takes
a spreadsheet import, and `entolog export -f irecord` writes exactly the columns
its importer offers. entolog is upstream of iRecord, not an alternative to it.

**iNaturalist** is a photo-first platform with community identification and
strong image recognition. It is excellent at *what is this*, which entolog does
not attempt at all. Two differences matter for a serious recorder: records live
on somebody else's server, and the default licence is non-commercial, which stops
some record centres using them. entolog keeps everything local and makes you
choose the licence deliberately.

**MapMate and Recorder 6** are desktop databases with a long history, especially
in the moth-recording community. They are Windows software of an older
generation. entolog is a few hundred kilobytes of standard-library Python that
runs anywhere and exports to open formats.

**A spreadsheet** is what most recorders actually use, and it is a perfectly good
answer. What it cannot do is read the date and position out of the photograph,
group a burst of shots into one specimen, autocomplete a name you typed last
week, or tell you that the camera clock was reset. That is the whole of what
entolog adds.

**NBN Record Cleaner** checks a finished spreadsheet against verification rules,
which are a body of expert knowledge entolog has no equivalent of. `entolog
check` is a smaller thing run earlier: the faults that are visible from the
photographs and your own taxon list, while the photographs are still in front of
you.

## What entolog does not do

- **It does not identify anything.** There is no image recognition and no
  suggestion of names. It records what you determine.
- **It ships no taxonomy of its own.** Load the taxon list you are entitled to
  use and entolog will check names against it, carry its identifiers into every
  export, and tell you when a record is filed under a synonym. It will not fetch
  a backbone for you and it will never rewrite a name you typed.
- **It does not store or publish records anywhere.** No account, no server, no
  sync. One SQLite file next to your photographs.
- **It does not do verification workflows.** No comments, no reviewers, no
  status. Send the records to a scheme that does.
- **It is not a photo manager.** It never writes to your images and never moves
  or copies them.

## If you are an organisation

The things that usually matter for evaluation:

- MIT licensed, no dependencies, one file to distribute, runs offline.
- Exports a Darwin Core Archive with `meta.xml` and `eml.xml`, and a stable
  `occurrenceID` that will not collide with anyone else's.
- The record schema is a JSON file, so a scheme can hand its recorders a profile
  with exactly the fields it wants back.
- Nothing leaves the machine unless the recorder runs `entolog locality lookup`,
  which is the only command that touches the network.
- 273 tests, run with `python3 -m unittest discover -s tests`, no network needed.
