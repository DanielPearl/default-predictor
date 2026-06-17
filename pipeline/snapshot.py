#!/usr/bin/env python3
"""
Append a point-in-time snapshot of the enriched `properties` table into an
append-only `parcel_history` table, capturing EVERY feature. Only parcels whose
features changed since their last snapshot are appended (change-detected), so
the history is a compact change-log rather than N identical copies per year.

History lives in its own data/history.db, isolated from the rebuildable
taxlots.db so a base refresh can never touch it. Run weekly on the droplet.
"""
import hashlib
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "taxlots.db"      # source: current enriched properties
HIST = ROOT / "data" / "history.db"    # append-only, never rebuilt


def row_hash(prop, cols):
    return hashlib.md5(json.dumps([prop[c] for c in cols], default=str).encode()).hexdigest()


def main(snap=None):
    snap = snap or date.today().isoformat()
    src = sqlite3.connect(DB)
    src.row_factory = sqlite3.Row
    props = [dict(r) for r in src.execute("SELECT * FROM properties")]
    if not props:
        print("no properties table to snapshot")
        return
    cols = list(props[0].keys())

    h = sqlite3.connect(HIST)
    hist_cols = ["snapshot_date"] + cols + ["row_hash"]
    h.execute("CREATE TABLE IF NOT EXISTS parcel_history (%s)" % ", ".join('"%s"' % x for x in hist_cols))
    h.execute("CREATE INDEX IF NOT EXISTS idx_hist_pid ON parcel_history(property_id)")
    h.execute("CREATE INDEX IF NOT EXISTS idx_hist_date ON parcel_history(snapshot_date)")

    last = dict(h.execute("""
        SELECT property_id, row_hash FROM parcel_history
        WHERE (property_id, snapshot_date) IN
          (SELECT property_id, MAX(snapshot_date) FROM parcel_history GROUP BY property_id)
    """).fetchall())

    appended = 0
    for p in props:
        rh = row_hash(p, cols)
        if last.get(p["property_id"]) == rh:
            continue  # unchanged since last snapshot
        h.execute("INSERT INTO parcel_history VALUES (%s)" % ",".join("?" * len(hist_cols)),
                  [snap] + [p[c] for c in cols] + [rh])
        appended += 1
    h.commit()

    total = h.execute("SELECT COUNT(*) FROM parcel_history").fetchone()[0]
    dates = h.execute("SELECT COUNT(DISTINCT snapshot_date) FROM parcel_history").fetchone()[0]
    print(f"snapshot {snap}: appended {appended} changed/new of {len(props)} parcels "
          f"({len(cols)} features each). history.db now {total} rows across {dates} snapshot dates")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
