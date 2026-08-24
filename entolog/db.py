"""SQLite store. One file holds the photos, the determinations and the vocabulary,
so a session survives a closed laptop and re-scanning a folder never loses typing."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS photos (
  id            INTEGER PRIMARY KEY,
  path          TEXT UNIQUE NOT NULL,
  filename      TEXT NOT NULL,
  rel_path      TEXT NOT NULL,
  fingerprint   TEXT NOT NULL,
  bytes         INTEGER,
  taken_at      TEXT,
  taken_source  TEXT,
  lat           REAL,
  lon           REAL,
  altitude      REAL,
  gps_accuracy_m REAL,
  orientation   INTEGER DEFAULT 1,
  camera        TEXT,
  lens          TEXT,
  width         INTEGER,
  height        INTEGER,
  thumb_offset  INTEGER,
  thumb_length  INTEGER,
  exif          TEXT,
  group_id      INTEGER,
  seq           INTEGER,
  added_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS photos_seq ON photos(seq);
CREATE INDEX IF NOT EXISTS photos_group ON photos(group_id);
CREATE INDEX IF NOT EXISTS photos_fp ON photos(fingerprint);

-- Records made before 1.1 lived here. Kept as the safety net that
-- _carry_over reads from; nothing writes to it any more.
CREATE TABLE IF NOT EXISTS records (
  photo_id   INTEGER PRIMARY KEY REFERENCES photos(id) ON DELETE CASCADE,
  species    TEXT DEFAULT '',
  stage      TEXT DEFAULT '',
  sex        TEXT DEFAULT '',
  comments   TEXT DEFAULT '',
  confidence TEXT DEFAULT '',
  flagged    INTEGER DEFAULT 0,
  updated_at TEXT
);

-- One row per photograph per field. Fields come from the profile, so a record
-- can hold whatever the recorder defined without a schema change.
CREATE TABLE IF NOT EXISTS field_values (
  photo_id   INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
  field      TEXT NOT NULL,
  value      TEXT NOT NULL DEFAULT '',
  updated_at TEXT,
  PRIMARY KEY (photo_id, field)
);
CREATE INDEX IF NOT EXISTS field_values_field ON field_values(field, value);

-- What has been typed into each field, for autocomplete, plus any imported list.
CREATE TABLE IF NOT EXISTS terms (
  field     TEXT NOT NULL,
  value     TEXT NOT NULL,
  uses      INTEGER DEFAULT 0,
  from_list INTEGER DEFAULT 0,
  note      TEXT DEFAULT '',
  PRIMARY KEY (field, value)
);

CREATE TABLE IF NOT EXISTS species (
  name       TEXT PRIMARY KEY,
  authority  TEXT DEFAULT '',
  vernacular TEXT DEFAULT '',
  family     TEXT DEFAULT '',
  uses       INTEGER DEFAULT 0,
  from_list  INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);

CREATE TABLE IF NOT EXISTS places (
  key      TEXT PRIMARY KEY,          -- position rounded to about 10 m
  lat      REAL, lon REAL,
  verbose  TEXT,                      -- whatever the lookup gave back
  short    TEXT,                      -- what goes in the record
  source   TEXT
);
"""

# Columns added after 1.0. SQLite has no IF NOT EXISTS for ALTER, so check first.
LATER = {"photos": {"locality": "TEXT", "locality_full": "TEXT", "gridref": "TEXT"}}


class Connection(sqlite3.Connection):
    """Carries its own path, so anything holding the handle can find the folder
    the records live in without being told twice."""
    path: Path = None


def connect(path: str | Path) -> Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cx = sqlite3.connect(path, timeout=30, factory=Connection)
    cx.row_factory = sqlite3.Row
    cx.path = path
    cx.executescript(SCHEMA)
    for table, cols in LATER.items():
        have = {r["name"] for r in cx.execute(f"PRAGMA table_info({table})")}
        for name, decl in cols.items():
            if name not in have:
                cx.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
    _carry_over(cx)
    cx.commit()
    return cx


def _carry_over(cx):
    """Records made before fields were user-defined lived in fixed columns.
    Move them across once, leaving the old table untouched as a safety net."""
    if get_meta(cx, "carried_over"):
        return
    old = {r["name"] for r in cx.execute("PRAGMA table_info(records)")}
    moved = 0
    for name in ("species", "stage", "sex", "comments", "confidence"):
        if name not in old:
            continue
        moved += cx.execute(
            "INSERT INTO field_values(photo_id, field, value, updated_at) "
            f"SELECT photo_id, ?, {name}, COALESCE(updated_at, datetime('now')) FROM records "
            f"WHERE COALESCE({name},'') != '' "
            "ON CONFLICT(photo_id, field) DO NOTHING", (name,)).rowcount
    if "flagged" in old:
        cx.execute("INSERT INTO field_values(photo_id, field, value, updated_at) "
                   "SELECT photo_id, '_flag', '1', datetime('now') FROM records "
                   "WHERE COALESCE(flagged,0)=1 ON CONFLICT(photo_id, field) DO NOTHING")
    for r in cx.execute("SELECT name, uses, vernacular FROM species"):
        cx.execute("INSERT INTO terms(field, value, uses, note) VALUES('species',?,?,?) "
                   "ON CONFLICT(field, value) DO NOTHING", (r["name"], r["uses"], r["vernacular"]))
    cx.commit()
    set_meta(cx, "carried_over", {"values": moved})


def get_meta(cx, key, default=None):
    row = cx.execute("SELECT v FROM meta WHERE k=?", (key,)).fetchone()
    return json.loads(row["v"]) if row else default


def set_meta(cx, key, value):
    cx.execute("INSERT INTO meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
               (key, json.dumps(value)))
    cx.commit()
