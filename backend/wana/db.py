"""SQLite storage for field records and reviews (swap for PostGIS when the pilot grows)."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import DB_PATH, ensure_dirs

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  client_id TEXT UNIQUE NOT NULL,          -- generated on the phone; makes offline re-sync idempotent
  sample_no TEXT NOT NULL,
  target_id TEXT,
  lon REAL NOT NULL, lat REAL NOT NULL, accuracy_m REAL,
  checks TEXT NOT NULL,                    -- JSON: {black_grains, heavy, brown_streak, green_host, old_pits}
  notes TEXT, photo TEXT,
  observer TEXT,
  created_at TEXT NOT NULL, received_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',  -- pending | endorsed | rejected
  lab_cr2o3 REAL, reviewer TEXT, reviewed_at TEXT, review_note TEXT,
  used_in_version INTEGER
);
"""


@contextmanager
def conn():
    ensure_dirs()
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    try:
        yield c
        c.commit()
    finally:
        c.close()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def row_to_dict(r):
    d = dict(r)
    d["checks"] = json.loads(d["checks"])
    return d


def retrain_from_db(note=""):
    from .model import _grid_from, latest_version, train
    from .stack import load_stack
    _, meta = load_stack()
    g = _grid_from(meta)
    with conn() as c:
        rows = [dict(r) for r in c.execute("SELECT id, lon, lat, status FROM records WHERE status IN ('endorsed','rejected')")]
    pres, absn = [], []
    for r in rows:
        rr, cc = g.from_lonlat([r["lon"]], [r["lat"]])
        if g.inside(rr, cc)[0]:
            (pres if r["status"] == "endorsed" else absn).append((int(rr[0]), int(cc[0])))
    parent = latest_version()
    model = train(pres, absn, note=note, parent=parent if parent >= 0 else None)
    with conn() as c:
        c.execute("UPDATE records SET used_in_version=? WHERE status IN ('endorsed','rejected') AND used_in_version IS NULL",
                  (model["version"],))
    return model
