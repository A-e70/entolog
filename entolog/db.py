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

CREATE TABLE IF NOT EXISTS species (
  name       TEXT PRIMARY KEY,
  authority  TEXT DEFAULT '',
  vernacular TEXT DEFAULT '',
  family     TEXT DEFAULT '',
  uses       INTEGER DEFAULT 0,
  from_list  INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cx = sqlite3.connect(path, timeout=30)
    cx.row_factory = sqlite3.Row
    cx.executescript(SCHEMA)
    return cx


def get_meta(cx, key, default=None):
    row = cx.execute("SELECT v FROM meta WHERE k=?", (key,)).fetchone()
    return json.loads(row["v"]) if row else default


def set_meta(cx, key, value):
    cx.execute("INSERT INTO meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
               (key, json.dumps(value)))
    cx.commit()


DEFAULT_VOCAB = {
    "stage": ["adult", "larva", "nymph", "pupa", "egg", "exuvia", "case", "mine", "gall"],
    "sex": ["", "male", "female", "worker", "queen", "unknown"],
    "confidence": ["", "certain", "probable", "aggregate", "needs dissection"],
}


def vocab(cx) -> dict:
    v = dict(DEFAULT_VOCAB)
    v.update(get_meta(cx, "vocab", {}) or {})
    return v
