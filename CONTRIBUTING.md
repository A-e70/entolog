# Contributing

Bug reports and pull requests are welcome.

## Licence, and signing off

entolog is MIT licensed. Every version already published stays MIT, and nothing
here changes that.

Two things are asked of a pull request.

**Sign off your commits.** `git commit -s` adds a line like

```
Signed-off-by: Jane Recorder <jane@example.org>
```

which is the [Developer Certificate of Origin](https://developercertificate.org),
version 1.1. It says you wrote the patch, or otherwise have the right to submit
it under this project's licence. Nothing to sign, no account, no paperwork.

**The terms your contribution arrives under.** By signing off you agree that your
contribution is licensed under the MIT licence, and that the copyright holder may
also distribute the project, including your contribution, under other licence
terms in future. You keep the copyright in what you wrote.

That second part is here so entolog can be offered on different terms later if an
organisation needs that, without having to track down every past contributor. It
is a stated condition of contributing rather than a signed agreement, and
anything turning on it commercially would want a proper contributor licence
agreement instead. If you would rather not agree to it, say so in the pull
request and we can work out what to do before anything is merged.

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
