"""Keyboard-only recording: a terminal loop, a status line for someone else's
image viewer, and the shared idea of "the photograph being looked at right now".

The grammar is the profile's. Fields in profile order separated by /, or
name=value in any order, or a bare line meaning just the primary field.
Commands are :vim style so nothing a recorder types as a species can ever be
mistaken for one.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

from . import db, records
from . import profile as P

DEFAULT_FORMAT = "{index} {filename}  {date} {time}  {where}| {record}"

HELP = """\
  Vespa crabro / adult / f / on ivy    fields in profile order, / between them
  Vespa crabro                         just the first field
  count=3 worn=fresh                   name=value, any order, any subset
  vecr                                 an abbreviation, if it can only mean one thing
  .            repeat the last record          -  clear this photograph's record
  #            flag for a second look          *  whole event on or off
  <  >         previous, next                  +  jump to what the viewer is showing
  :n 12        go to number 12                 :s show the full record
  :f todo      filter: todo all done flagged nogps
  :l [n]       the last n rows of the table    :w [file] write the table now
  :h           this help                       :q quit
"""


# --------------------------------------------------------------------------
# what the viewer is showing
def find(cx, target: str):
    """A photograph by id, full path or filename. Raises LookupError if it is
    not there or if a bare filename is ambiguous."""
    s = str(target).strip()
    if s.isdigit():
        row = cx.execute("SELECT * FROM photos WHERE id=?", (int(s),)).fetchone()
        if row is None:
            raise LookupError(f"no photograph numbered {s}")
        return row
    row = cx.execute("SELECT * FROM photos WHERE path=?", (s,)).fetchone()
    if row is None:
        row = cx.execute("SELECT * FROM photos WHERE path=?",
                         (str(Path(s).expanduser().resolve()),)).fetchone()
    if row is None:
        name = Path(s).name
        hits = cx.execute("SELECT * FROM photos WHERE filename=? ORDER BY seq",
                          (name,)).fetchall()
        if len(hits) > 1:
            raise LookupError(f"{name} matches {len(hits)} photographs, give the full path")
        row = hits[0] if hits else None
    if row is None:
        raise LookupError(f"{s} is not in this database. Has it been scanned?")
    return row


def set_current(cx, target: str):
    """Point entolog at the photograph a viewer is showing."""
    row = find(cx, target)
    db.set_meta(cx, "current_photo", row["id"])
    return row


def get_current(cx):
    pid = db.get_meta(cx, "current_photo")
    if pid is None:
        return None
    return cx.execute("SELECT * FROM photos WHERE id=?", (pid,)).fetchone()


# --------------------------------------------------------------------------
# the status line, for a viewer to display
def _get(photo, key, default=""):
    """Photo rows arrive either as sqlite3.Row or as the dicts the list builds."""
    try:
        v = photo[key]
    except (KeyError, IndexError):
        return default
    return default if v is None else v


def record_summary(prof, values: dict) -> str:
    parts = [values.get(f["name"], "") for f in prof["fields"]
             if f["type"] != "multiline"]
    return " ".join(p for p in parts if p)


def status_line(cx, prof, photo, i=None, n=None, fmt=None) -> str:
    values = records.values(cx, photo["id"])
    taken = _get(photo, "taken_at")
    date, _, time = taken.partition("T")
    where = _get(photo, "locality")
    if _get(photo, "gridref"):
        gr = _get(photo, "gridref")
        where = f"{where} {gr}" if where else gr
    fields = {
        "i": "" if i is None else i, "n": "" if n is None else n,
        "index": "" if i is None or n is None else f"{i}/{n}",
        "filename": _get(photo, "filename"), "path": _get(photo, "path"),
        "date": date, "time": time[:8], "datetime": taken,
        "locality": _get(photo, "locality"), "gridref": _get(photo, "gridref"),
        "where": (where + "  ") if where else "",
        "lat": f"{photo['lat']:.5f}" if _get(photo, "lat", None) is not None else "",
        "lon": f"{photo['lon']:.5f}" if _get(photo, "lon", None) is not None else "",
        "position": (f"{photo['lat']:.5f}, {photo['lon']:.5f}"
                     if _get(photo, "lat", None) is not None else ""),
        "event": _get(photo, "group_id"), "camera": _get(photo, "camera"),
        "record": record_summary(prof, values),
        "flag": "*" if values.get(records.FLAG) == "1" else "",
    }
    for f in prof["fields"]:
        fields.setdefault(f["name"], values.get(f["name"], ""))
    out = (fmt or db.get_meta(cx, "status_format") or DEFAULT_FORMAT)
    return _format(out, fields)


class _Blanks(dict):
    def __missing__(self, k):
        return ""


def _format(fmt: str, fields: dict) -> str:
    try:
        return fmt.format_map(_Blanks(fields)).strip()
    except (ValueError, IndexError):
        return fmt


# --------------------------------------------------------------------------
# resolving what was typed into what the field allows
def resolve(cx, prof, name: str, text: str):
    """(value, note, candidates). Candidates non-empty means it was ambiguous and
    nothing should be written until the recorder picks one. A name is only ever
    replaced when exactly one thing could have been meant, and the note says so.
    The window offers the same list, from the same place."""
    f = P.field(prof, name)
    text = (text or "").strip()
    if not text or f is None:
        return text, "", []
    if f["choices"]:
        low = text.lower()
        exact = [c for c in f["choices"] if c and c.lower() == low]
        if exact:
            return exact[0], "", []
        hits = [c for c in f["choices"] if c and c.lower().startswith(low)]
        if len(hits) == 1:
            return hits[0], (f"{text} -> {hits[0]}" if hits[0].lower() != low else ""), []
        if len(hits) > 1:
            return text, "", hits
        return text, "", []
    if not f["learn"]:
        return text, "", []

    known = records.known_values(cx, name)
    for value in known:
        if value.lower() == text.lower():
            return value, "", []                 # already a name, only the case differs
    if " " in text or len(text) > 12:
        return text, "", []                      # a real name, typed out. Leave it alone
    hits = records.suggest(cx, name, text, limit=40)
    if not hits:
        return text, "", []
    best = hits[0]["rank"]
    shortlist = [h["value"] for h in hits if h["rank"] == best]
    if len(shortlist) == 1:
        return shortlist[0], f"{text} -> {shortlist[0]}", []
    return text, "", shortlist[:12]


# --------------------------------------------------------------------------
# the grammar
ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def parse(prof, line: str):
    """Returns (kind, payload). kind is one of: blank, command, fields, error."""
    line = line.strip()
    if not line:
        return "blank", None
    if line[0] in ":.-#*<>+?":
        if line[0] == ":":
            parts = line[1:].split(None, 1)
            return "command", (parts[0].lower() if parts else "", parts[1] if len(parts) > 1 else "")
        return "command", ({"?": "h"}.get(line[0], line[0]), line[1:].strip())
    names = P.names(prof)
    order = prof.get("entry", {}).get("order") or names
    if "/" in line:
        segs = line.split("/")
        if len(segs) > len(order):
            return "error", (f"{len(segs)} parts but the profile has {len(order)} fields: "
                             f"{' / '.join(order)}")
        out = {}
        for name, seg in zip(order, segs):
            seg = seg.strip()
            if seg == "":
                continue                          # left as it was
            out[name] = "" if seg == "-" else seg
        return "fields", out
    if ASSIGN.match(line):
        out = {}
        try:
            tokens = shlex.split(line)
        except ValueError:
            tokens = line.split()
        current = None
        for t in tokens:
            if ASSIGN.match(t):
                key, _, val = t.partition("=")
                if key not in names:
                    return "error", f"there is no field called {key!r}. Fields: {', '.join(names)}"
                current = key
                out[key] = val
            elif current:
                out[current] = (out[current] + " " + t).strip()
            else:
                return "error", f"{t!r} came before any field name"
        return "fields", out
    return "fields", {prof["primary"]: line}


# --------------------------------------------------------------------------
def record_one(cx, prof, photo, line, group=False) -> tuple:
    """Apply one line, or a ready made {field: value}, to one photograph.
    Returns (messages, ids touched, values written, errors)."""
    if isinstance(line, dict):
        payload = dict(line)
    else:
        kind, payload = parse(prof, line)
        if kind == "error":
            return [payload], [], {}, {"_": payload}
        if kind != "fields":
            return ["that is a command, not a record"], [], {}, {"_": "not a record"}
    say, clean = [], {}
    for name, raw in payload.items():
        value, note, candidates = resolve(cx, prof, name, raw)
        if candidates:
            msg = f"{raw!r} could be: {', '.join(candidates)}. Type more of it."
            return [msg], [], {}, {name: msg}
        if note:
            say.append(note)
        clean[name] = value
    ids, errors = records.save(cx, prof, photo["id"], clean, apply_group=group)
    for f, err in errors.items():
        say.append(f"{f}: {err}")
    return say, ids, clean, errors


class Session:
    """Everything the terminal loop needs, with no terminal in it, so it can be
    driven by a test as easily as by a person."""

    def __init__(self, cx, prof=None, flt="todo", per_photo=False, follow=False):
        self.cx = cx
        self.prof = prof or P.active(cx)
        self.filter = flt
        self.group = not per_photo
        self.follow = follow
        self.last = {}
        self.i = 0
        self.reload()

    # -- moving about ----------------------------------------------------
    def reload(self, keep_id=None):
        self.photos = records.list_photos(self.cx, self.prof, self.filter, limit=10 ** 9)
        if keep_id is not None:
            j = next((k for k, p in enumerate(self.photos) if p["id"] == keep_id), None)
            self.i = j if j is not None else min(self.i, max(0, len(self.photos) - 1))
        self.i = max(0, min(self.i, max(0, len(self.photos) - 1)))

    @property
    def photo(self):
        return self.photos[self.i] if self.photos else None

    def move(self, delta: int) -> bool:
        j = self.i + delta
        if 0 <= j < len(self.photos):
            self.i = j
            return True
        return False

    def goto_id(self, pid) -> bool:
        j = next((k for k, p in enumerate(self.photos) if p["id"] == pid), None)
        if j is None:
            return False
        self.i = j
        return True

    def advance(self):
        """After a record: the next photograph still to do, skipping the rest of
        this event when a whole event was just recorded."""
        p = self.photo
        if p is None:
            return
        primary = self.prof["primary"]
        start = self.i + 1
        if self.group:
            while start < len(self.photos) and self.photos[start]["group_id"] == p["group_id"]:
                start += 1
        for k in range(start, len(self.photos)):
            if not self.photos[k]["values"].get(primary):
                self.i = k
                return
        self.i = min(start, len(self.photos) - 1) if self.photos else 0

    def event_size(self) -> int:
        p = self.photo
        return sum(1 for x in self.photos if p and x["group_id"] == p["group_id"])

    # -- the one entry point ---------------------------------------------
    def handle(self, line: str) -> dict:
        """Act on one typed line. Returns {say: [...], quit: bool, moved: bool}."""
        say, quit_ = [], False
        kind, payload = parse(self.prof, line)
        if kind == "blank":
            self.move(1)
        elif kind == "error":
            say.append(payload)
        elif kind == "command":
            cmd, arg = payload
            quit_, more = self._command(cmd, arg)
            say += more
        else:
            say += self._record(payload)
        return {"say": say, "quit": quit_}

    def _record(self, fields: dict) -> list:
        p = self.photo
        if p is None:
            return ["nothing to record against"]
        say, ids, clean, errors = record_one(self.cx, self.prof, p, fields,
                                             group=self.group)
        for pid in ids:
            row = next((x for x in self.photos if x["id"] == pid), None)
            if row is not None:
                row["values"].update({k: v for k, v in clean.items() if k != records.FLAG})
        self.last = {k: v for k, v in clean.items() if v and k != records.FLAG} or self.last
        if ids:                      # an ambiguous name saves nothing, and says why
            say.append(f"saved {len(ids)} photograph{'s' if len(ids) != 1 else ''}: "
                       f"{record_summary(self.prof, self.photo['values'])}")
        if not errors:
            self.advance()
        return say

    def _command(self, cmd: str, arg: str) -> tuple:
        p = self.photo
        if cmd in ("q", "quit", "wq", "x"):
            return True, (["written"] if cmd in ("wq", "x") else [])
        if cmd in ("h", "help"):
            return False, [HELP]
        if cmd == ".":
            return False, (self._record(dict(self.last)) if self.last
                           else ["nothing recorded yet to repeat"])
        if cmd == "-":
            if p is None:
                return False, []
            blank = {f["name"]: "" for f in self.prof["fields"]}
            records.save(self.cx, self.prof, p["id"], blank, apply_group=self.group)
            p["values"].clear()
            return False, ["cleared"]
        if cmd == "#":
            if p is None:
                return False, []
            on = p["flagged"] != 1
            records.save(self.cx, self.prof, p["id"], {records.FLAG: "1" if on else ""},
                         apply_group=False)
            p["flagged"] = 1 if on else 0
            return False, ["flagged" if on else "unflagged"]
        if cmd == "*":
            self.group = not self.group
            return False, [f"whole event {'on' if self.group else 'off'}"]
        if cmd == "<":
            return False, ([] if self.move(-1) else ["at the first one"])
        if cmd == ">":
            return False, ([] if self.move(1) else ["at the last one"])
        if cmd == "+":
            row = get_current(self.cx)
            if row is None:
                return False, ["the viewer has not said what it is showing"]
            if self.goto_id(row["id"]):
                return False, []
            self.filter = "all"
            self.reload()
            return False, ([] if self.goto_id(row["id"]) else ["that photograph is not listed"])
        if cmd in ("n", "no"):
            try:
                self.i = max(0, min(int(arg) - 1, len(self.photos) - 1))
            except ValueError:
                return False, ["give a number, as in :n 12"]
            return False, []
        if cmd in ("f", "filter"):
            if arg not in ("todo", "all", "done", "flagged", "nogps"):
                return False, ["filters: todo all done flagged nogps"]
            self.filter = arg
            self.reload(keep_id=p["id"] if p else None)
            return False, [f"{len(self.photos)} photographs"]
        if cmd == "s":
            if p is None:
                return False, []
            v = records.values(self.cx, p["id"])
            return False, [f"  {f['label']:12} {v.get(f['name'], '') or '-'}"
                           for f in self.prof["fields"]]
        if cmd in ("l", "list"):
            try:
                n = int(arg) if arg else 10
            except ValueError:
                n = 10
            from . import export
            rows = export.render(self.cx, "tsv").splitlines()
            return False, rows[:1] + rows[-n:] if len(rows) > 1 else ["nothing recorded yet"]
        if cmd in ("w", "write"):
            from . import export
            path = Path(arg).expanduser() if arg else _default_tsv(self.cx)
            path.write_text(export.render(self.cx, "tsv"), encoding="utf-8")
            return False, [f"wrote {path}"]
        return False, [f"no command :{cmd}. :h for the list"]


def _default_tsv(cx) -> Path:
    base = Path(getattr(cx, "path", "entolog.db"))
    return base.with_suffix(".tsv")


# --------------------------------------------------------------------------
def prompt_for(session) -> str:
    p = session.photo
    if p is None:
        return "(nothing to show) > "
    line = status_line(session.cx, session.prof, p, session.i + 1, len(session.photos))
    extra = f"  [event {p['group_id']}, {session.event_size()} shot(s)]" if session.group else ""
    return f"\n{line}{extra}\n> "


def run(cx, prof=None, flt="todo", per_photo=False, follow=False, out=print) -> int:
    """The interactive loop. Everything it does lives in Session, so this is only
    the reading and the printing."""
    session = Session(cx, prof, flt, per_photo, follow)
    _readline(cx, session)
    out(f"entolog, profile {session.prof['name']}: "
        f"{', '.join(P.names(session.prof))}")
    out(f"{len(session.photos)} photographs in filter {session.filter!r}. :h for help, :q to stop.")
    while True:
        if follow:
            row = get_current(cx)
            if row is not None and (session.photo is None or row["id"] != session.photo["id"]):
                if not session.goto_id(row["id"]):
                    session.filter = "all"
                    session.reload()
                    session.goto_id(row["id"])
        try:
            line = input(prompt_for(session))
        except (EOFError, KeyboardInterrupt):
            out("")
            break
        res = session.handle(line)
        for s in res["say"]:
            out(s)
        if res["quit"]:
            break
    from . import export
    out(export.summary(cx, session.prof))
    return 0


def _readline(cx, session):
    """History and tab completion, when the terminal has readline."""
    try:
        import readline
    except ImportError:
        return

    def complete(text, state):
        buf = readline.get_line_buffer()
        names = P.names(session.prof)
        field = session.prof["primary"]
        if "/" in buf:
            idx = buf.count("/")
            field = names[idx] if idx < len(names) else names[-1]
        elif "=" in buf:
            field = buf.rsplit("=", 1)[0].split()[-1]
        f = P.field(session.prof, field)
        if f and f["choices"]:
            hits = [c for c in f["choices"] if c and c.lower().startswith(text.lower())]
        else:
            hits = [r["value"] for r in cx.execute(
                "SELECT value FROM terms WHERE field=? AND value LIKE ? "
                "ORDER BY uses DESC, value LIMIT 40", (field, text + "%"))]
        return hits[state] if state < len(hits) else None

    readline.set_completer(complete)
    readline.set_completer_delims(" \t/=")
    readline.parse_and_bind("tab: complete")
