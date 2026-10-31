#!/usr/bin/env python3
"""
Launch the DuckDB UI -- a local web database browser -- over this project's data.

Opens the analytical warehouse (data/warehouse.duckdb) and attaches the SQLite
serving DB (data/taxlots.db) read-only, so you can browse and query both in one
place. The UI runs locally (default http://localhost:4213); nothing is exposed
to the internet. Leave this process running while you use the UI; Ctrl-C to stop.

    .venv/bin/python tools/view_db.py

On the droplet, run it there and reach the UI over an SSH tunnel:
    ssh -L 4213:localhost:4213 your-user@your-droplet
"""
import shutil
import time
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE = ROOT / "data" / "warehouse.duckdb"
WAREHOUSE_SNAP = ROOT / "data" / "warehouse_view.duckdb"
TAXLOTS = ROOT / "data" / "taxlots.db"

# DuckDB is single-writer: a build holds a write lock on warehouse.duckdb, which
# would block (or be blocked by) the viewer. So view a read-only SNAPSHOT copy --
# the viewer never fights a running dbt build. Re-run this script to refresh it.
if WAREHOUSE.exists():
    shutil.copy2(WAREHOUSE, WAREHOUSE_SNAP)
    print(f"snapshot: {WAREHOUSE_SNAP.name} (refresh by re-running this script)")

con = duckdb.connect(str(WAREHOUSE_SNAP), read_only=True)
con.execute("INSTALL ui")
con.execute("LOAD ui")

if TAXLOTS.exists():
    try:
        con.execute("INSTALL sqlite")
        con.execute("LOAD sqlite")
        con.execute(f"ATTACH '{TAXLOTS}' AS taxlots (TYPE sqlite, READ_ONLY)")
        print(f"attached taxlots.db (SQLite, read-only)")
    except Exception as e:  # noqa: BLE001
        print(f"could not attach taxlots.db: {e}")

con.execute("CALL start_ui()")
print("DuckDB UI running at http://localhost:4213  (Ctrl-C to stop)", flush=True)

try:
    while True:
        time.sleep(3600)
except KeyboardInterrupt:
    print("stopping DuckDB UI")
