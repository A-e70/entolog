"""Recording profiles: the fields a record has, as data rather than as code.

A profile lists the fields the recorder fills in. Everything downstream is
generated from it: the storage, the form in the window, the keyboard shortcuts,
the autocomplete, the validation and the export columns. Changing what a record
contains is editing a JSON file, not editing entolog.

The active profile is copied into the database, so a set of records always
carries the definition it was made under and stays readable later.
"""

from __future__ import annotations

import json
from pathlib import Path

BUILTIN = ("insects", "wildlife", "plants")

# The window and the keyboard already use these, so a field may not claim one.
RESERVED_KEYS = set("jkdgfe/?<>") | {"enter", "escape", "tab"}

TYPES = ("text", "choice", "number", "multiline", "date", "bool")

FIELD_DEFAULTS = {
    "label": None, "type": "text", "choices": None, "open": True, "required": False,
    "key": None, "digits": False, "learn": False, "default": "", "dwc": "",
    "help": "", "primary": False, "min": None, "max": None,
}


class ProfileError(ValueError):
    pass


def _read(path_or_name) -> dict:
    if isinstance(path_or_name, dict):
        return json.loads(json.dumps(path_or_name))       # copy, never share state
    s = str(path_or_name)
    if s in BUILTIN:
        try:
            from importlib.resources import files
            return json.loads(files("entolog").joinpath(f"profiles/{s}.json")
                              .read_text(encoding="utf-8"))
        except Exception:
            p = Path(__file__).parent / "profiles" / f"{s}.json"
            return json.loads(p.read_text(encoding="utf-8"))
    p = Path(s).expanduser()
    if not p.exists():
        raise ProfileError(f"no profile called {s!r}. Built in: {', '.join(BUILTIN)}, "
                           f"or give a path to a .json file")
    return json.loads(p.read_text(encoding="utf-8"))


def load(source) -> dict:
    """Read a profile by built-in name, path or dict, fill defaults, validate."""
    prof = _read(source)
    prof.setdefault("name", "custom")
    prof.setdefault("title", prof["name"])
    prof.setdefault("version", 1)
    out_fields = []
    for raw in prof.get("fields", []):
        if isinstance(raw, str):                          # "species" is a valid shorthand
            raw = {"name": raw}
        f = dict(FIELD_DEFAULTS, **raw)
        f["label"] = f["label"] or f["name"].replace("_", " ")
        if f["type"] == "choice" and f["choices"] is None:
            f["choices"] = []
        if f["type"] == "bool" and not f["choices"]:
            f["choices"] = ["", "yes", "no"]
        if f["key"]:
            f["key"] = str(f["key"]).lower()
        out_fields.append(f)
    prof["fields"] = out_fields
    if not prof.get("primary"):
        first = next((f["name"] for f in out_fields if f["primary"]),
                     out_fields[0]["name"] if out_fields else None)
        prof["primary"] = first
    for f in out_fields:
        f["primary"] = f["name"] == prof["primary"]
    prof.setdefault("export", {})
    prof["export"].setdefault("columns", default_columns(prof))
    errors = validate(prof)
    if errors:
        raise ProfileError("this profile cannot be used:\n  " + "\n  ".join(errors))
    return prof


PHOTO_FIELDS = ("filename", "date", "time", "datetime", "latitude", "longitude", "position",
                "locality", "gridref", "altitude_m", "coord_uncertainty_m", "group",
                "date_source", "camera", "lens", "folder", "path", "record_number")


def default_columns(prof) -> list:
    return (["filename", "date", "time", "latitude", "longitude"]
            + [f["name"] for f in prof.get("fields", [])])


def validate(prof) -> list:
    errors, seen, keys, digits = [], set(), {}, []
    if not prof.get("fields"):
        errors.append("a profile needs at least one field")
    for f in prof.get("fields", []):
        n = f.get("name", "")
        if not n or not n.replace("_", "").isalnum() or n[0].isdigit():
            errors.append(f"{n!r} is not a usable field name: letters, digits and _ only")
        if n.startswith("_"):
            errors.append(f"{n!r}: names starting with _ are kept for entolog's own use")
        if n in seen:
            errors.append(f"{n!r} is defined twice")
        if n in PHOTO_FIELDS:
            errors.append(f"{n!r} already comes from the photograph, choose another name")
        seen.add(n)
        if f.get("type") not in TYPES:
            errors.append(f"{n}: type {f.get('type')!r} is not one of {', '.join(TYPES)}")
        if f.get("type") == "choice" and not f.get("choices"):
            errors.append(f"{n}: a choice field needs a list of choices")
        k = f.get("key")
        if k:
            if len(k) != 1 or k in RESERVED_KEYS:
                taken = ", ".join(sorted(x for x in RESERVED_KEYS if len(x) == 1))
                errors.append(f"{n}: key {k!r} is not free, entolog already uses {taken}")
            if k in keys:
                errors.append(f"{n}: key {k!r} is already taken by {keys[k]}")
            keys[k] = n
        if f.get("digits"):
            digits.append(n)
            if f.get("type") != "choice":
                errors.append(f"{n}: only a choice field can take the number keys")
            if len(f.get("choices") or []) > 9:
                errors.append(f"{n}: more than nine choices, so the number keys "
                              f"cannot reach them all")
    if len(digits) > 1:
        errors.append("only one field can take the number keys, got " + ", ".join(digits))
    if prof.get("primary") not in seen and prof.get("fields"):
        errors.append(f"primary field {prof.get('primary')!r} is not one of the fields")
    for c in prof.get("export", {}).get("columns", []):
        if c not in seen and c not in PHOTO_FIELDS:
            errors.append(f"export column {c!r} is neither a field nor part of the photograph")
    return errors


def names(prof) -> list:
    return [f["name"] for f in prof["fields"]]


def field(prof, name):
    return next((f for f in prof["fields"] if f["name"] == name), None)


def clean(prof, name, value):
    """Coerce and check one value. Returns (value, error or None)."""
    f = field(prof, name)
    if f is None:
        return None, f"there is no field called {name!r}"
    v = "" if value is None else str(value).strip()
    if not v:
        return "", ("this field is required" if f["required"] else None)
    if f["type"] == "number":
        try:
            n = float(v)
        except ValueError:
            return v, f"{f['label']} takes a number"
        if f["min"] is not None and n < f["min"]:
            return v, f"{f['label']} cannot be below {f['min']}"
        if f["max"] is not None and n > f["max"]:
            return v, f"{f['label']} cannot be above {f['max']}"
        return (str(int(n)) if n == int(n) else str(n)), None
    if f["type"] == "choice" and not f["open"] and v not in f["choices"]:
        return v, f"{f['label']} must be one of: {', '.join(c for c in f['choices'] if c)}"
    if f["type"] == "bool":
        return ("yes" if v.lower() in ("1", "true", "yes", "y", "on") else "no"), None
    return v, None


# --------------------------------------------------------------------------
def active(cx) -> dict:
    """The profile this database was recorded under, defaulting to insects."""
    row = cx.execute("SELECT v FROM meta WHERE k='profile'").fetchone()
    if row:
        return load(json.loads(row["v"]))
    prof = load("insects")
    set_active(cx, prof)
    return prof


def set_active(cx, source, force=False) -> dict:
    """Adopt a profile. Refuses to drop a field that already holds records."""
    prof = source if isinstance(source, dict) and "fields" in source else load(source)
    prof = load(prof)
    old = cx.execute("SELECT v FROM meta WHERE k='profile'").fetchone()
    if old and not force:
        losing = []
        keep = set(names(prof))
        for f in load(json.loads(old["v"]))["fields"]:
            if f["name"] in keep:
                continue
            n = cx.execute("SELECT COUNT(*) c FROM field_values WHERE field=? AND value!=''",
                           (f["name"],)).fetchone()["c"]
            if n:
                losing.append(f"{f['name']} ({n} record{'s' if n != 1 else ''})")
        if losing:
            raise ProfileError(
                "this profile drops fields that already hold records: "
                + ", ".join(losing)
                + ".\nThe values stay in the database either way, but they would stop being "
                  "shown or exported. Repeat with --force if that is what you want.")
    cx.execute("INSERT INTO meta(k,v) VALUES('profile',?) "
               "ON CONFLICT(k) DO UPDATE SET v=excluded.v", (json.dumps(prof, indent=2),))
    cx.commit()
    return prof
