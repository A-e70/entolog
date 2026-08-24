# Contributing

Bug reports and pull requests are welcome.

## Running it from source

```bash
git clone https://github.com/A-e70/entolog && cd entolog
python3 -m entolog demo
python3 -m unittest discover -s tests
```

Python 3.9 or newer. No packages to install, for the tests either.

## Three rules that come before anything else

1. **No dependencies.** Standard library only. Pillow and exiftool are optional
   preview helpers, and every path must still work when both are absent. Please
   do not add a framework, a bundler or a package to make something a little
   nicer.
2. **Never lose or invent a record.** Scans are idempotent. A record survives a
   renamed file. A value that fails validation is stored anyway with the
   complaint shown. Switching profile never deletes a value. Anything uncertain
   is labelled rather than filled in.
3. **Nothing below the surface knows what the fields are.** Fields come from the
   active profile. If you find yourself writing `species` or `stage` anywhere
   outside `entolog/profiles/*.json` and the tests, something has gone wrong.

## Tests

Every change needs one. The suite builds its own JPEGs, so it needs no camera and
no network.

```bash
python3 -m unittest discover -s tests        # all of it
python3 -m unittest tests.test_profile -v    # one file
```

The window needs a real browser, which the Python tests cannot check. If you
change `entolog/web/app.html`, start a server and look at it, with a profile that
is **not** the default:

```bash
python3 -m entolog demo --no-open
cd entolog-demo && python3 -m entolog profile use moths --force
python3 -m entolog annotate
```

## Style

Match what is there. Comments explain why, not what. No em dashes.

## Things that would help

- Profiles for groups that are not covered: hoverflies, spiders, bryophytes,
  freshwater invertebrates. A profile is a JSON file, so this needs no code.
- Grid reference systems other than OSGB: Irish grid, MGRS, UTM.
- Reading EXIF from HEIC without exiftool.
- Translations of the window.
