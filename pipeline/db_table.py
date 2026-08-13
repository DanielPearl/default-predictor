#!/usr/bin/env python3
"""
Bridge between the enrichment JSON and a queryable `properties` table in the
database, so the website's table is served *from* the DB.

  load   : read properties_sample.json -> (re)create the `properties` table
  export : dump the `properties` table -> properties_sample.json (served file)

On the droplet: enrichment writes the JSON, `load` puts it in the DB, and
`export <web-root>/properties_sample.json` produces the file nginx serves, so
the page reflects exactly what's in the droplet database.
"""
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "taxlots.db"
JSON = ROOT / "properties_sample.json"


def columns(props):
    keys = ["scraped_date"]
    for p in props:
        for k in p:
            if k not in keys:
                keys.append(k)
    return keys


def load():
    """One-time REPLACE: drop and recreate the properties table with this
    scrape (each row stamped with today's scrape date)."""
    props = json.loads(JSON.read_text())
    keys = columns(props)
    sd = date.today().isoformat()
    c = sqlite3.connect(DB)
    c.execute("DROP TABLE IF EXISTS properties")
    c.execute("CREATE TABLE properties (%s)" % ", ".join('"%s"' % k for k in keys))
    c.executemany("INSERT INTO properties VALUES (%s)" % ",".join("?" * len(keys)),
                  [tuple(sd if k == "scraped_date" else p.get(k) for k in keys) for p in props])
    c.execute("CREATE INDEX IF NOT EXISTS idx_prop ON properties(property_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_prop_date ON properties(scraped_date)")
    c.commit()
    print(f"loaded (REPLACE) {len(props)} rows x {len(keys)} cols; scraped_date {sd}")


def append():
    """APPEND this scrape onto the existing properties table (accumulate over
    time). Aligns to the existing schema; creates the table if missing."""
    c = sqlite3.connect(DB)
    existing = [r[1] for r in c.execute("PRAGMA table_info(properties)")]
    if not existing:
        return load()
    props = json.loads(JSON.read_text())
    sd = date.today().isoformat()
    c.executemany(
        "INSERT INTO properties (%s) VALUES (%s)" % (
            ",".join('"%s"' % k for k in existing), ",".join("?" * len(existing))),
        [tuple(sd if k == "scraped_date" else p.get(k) for k in existing) for p in props])
    c.commit()
    total = c.execute("SELECT COUNT(*) FROM properties").fetchone()[0]
    print(f"appended {len(props)} rows (scraped_date {sd}); properties now {total} total")


def export(out=None):
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    rows = [dict(r) for r in c.execute("SELECT * FROM properties ORDER BY scraped_date DESC, property_id")]
    (Path(out) if out else JSON).write_text(json.dumps(rows, indent=1))
    print(f"exported {len(rows)} rows -> {out or JSON}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "load"
    {"load": load, "append": append,
     "export": lambda: export(sys.argv[2] if len(sys.argv) > 2 else None)}[cmd]()
