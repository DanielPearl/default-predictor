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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "taxlots.db"
JSON = ROOT / "properties_sample.json"


def columns(props):
    keys = []
    for p in props:
        for k in p:
            if k not in keys:
                keys.append(k)
    return keys


def load():
    props = json.loads(JSON.read_text())
    keys = columns(props)
    c = sqlite3.connect(DB)
    c.execute("DROP TABLE IF EXISTS properties")
    c.execute("CREATE TABLE properties (%s)" % ", ".join('"%s"' % k for k in keys))
    c.executemany("INSERT INTO properties VALUES (%s)" % ",".join("?" * len(keys)),
                  [tuple(p.get(k) for k in keys) for p in props])
    if "property_id" in keys:
        c.execute("CREATE INDEX idx_prop ON properties(property_id)")
    c.commit()
    print(f"loaded {len(props)} rows x {len(keys)} columns into properties table")


def scrape_date():
    """The date this data was captured = the latest history snapshot; falls
    back to today if history.db isn't present yet."""
    try:
        h = sqlite3.connect(ROOT / "data" / "history.db")
        d = h.execute("SELECT MAX(snapshot_date) FROM parcel_history").fetchone()[0]
        if d:
            return d
    except Exception:  # noqa: BLE001
        pass
    from datetime import date
    return date.today().isoformat()


def export(out=None):
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    sd = scrape_date()
    rows = [{"scraped_date": sd, **dict(r)} for r in c.execute("SELECT * FROM properties")]
    Path(out).write_text(json.dumps(rows, indent=1)) if out else JSON.write_text(json.dumps(rows, indent=1))
    print(f"exported {len(rows)} rows (scraped_date {sd}) -> {out or JSON}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "load"
    {"load": load, "export": lambda: export(sys.argv[2] if len(sys.argv) > 2 else None)}[cmd]()
