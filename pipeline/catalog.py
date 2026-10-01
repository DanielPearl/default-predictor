#!/usr/bin/env python3
"""
Lake catalog database (data/lake.db).

One thin module for the catalog that indexes everything landed in the data
lake. Keeps schema in versioned SQL migrations (pipeline/migrations/) so the
database is reproducible and the eventual SQLite -> Postgres move is a
connection change, not a rewrite.

CLI:
    python3 pipeline/catalog.py migrate          # create/upgrade the schema
    python3 pipeline/catalog.py export [path]    # write uploads.json for the site
    python3 pipeline/catalog.py list             # print recent uploads

Stdlib only.
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = Path(os.environ.get("LAKE_DB", ROOT / "data" / "lake.db"))
MIGRATIONS = Path(__file__).resolve().parent / "migrations"
DEFAULT_EXPORT = ROOT / "uploads.json"


def connect():
    """Single place that knows the engine. Swap here for Postgres later."""
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")       # readers never block the writer
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def migrate(conn=None):
    """Apply any migration files not yet recorded, in filename order."""
    own = conn is None
    conn = conn or connect()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations "
                     "(version TEXT PRIMARY KEY, applied_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
        for f in sorted(MIGRATIONS.glob("*.sql")):
            if f.name in done:
                continue
            conn.executescript(f.read_text())
            conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (f.name,))
            conn.commit()
            print(f"applied {f.name}")
    finally:
        if own:
            conn.close()


def record_upload(**row):
    """Insert or replace the catalog row for one landed file.

    Keyed on (source, dataset, captured_date): re-running a week overwrites
    that week's row rather than duplicating it.
    """
    cols = ["source", "dataset", "captured_date", "filename", "relpath",
            "source_url", "content_type", "rows", "bytes", "sha256",
            "status", "fetched_at", "duration_s", "notes"]
    vals = [row.get(c) for c in cols]
    conn = connect()
    try:
        migrate(conn)
        conn.execute(
            "INSERT INTO lake_uploads (%s) VALUES (%s) "
            "ON CONFLICT(source, dataset, captured_date) DO UPDATE SET %s" % (
                ",".join(cols),
                ",".join("?" * len(cols)),
                ",".join(f"{c}=excluded.{c}" for c in cols if c not in
                         ("source", "dataset", "captured_date"))),
            vals)
        conn.commit()
    finally:
        conn.close()


def list_uploads(limit=500):
    conn = connect()
    try:
        migrate(conn)
        rows = conn.execute(
            "SELECT source, dataset, captured_date, filename, relpath, source_url, "
            "content_type, rows, bytes, sha256, status, fetched_at, duration_s, notes "
            "FROM lake_uploads ORDER BY captured_date DESC, id DESC LIMIT ?",
            (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def export_json(path=DEFAULT_EXPORT):
    path = Path(path)
    path.write_text(json.dumps(list_uploads(), indent=2))
    print(f"wrote {path} ({len(list_uploads())} rows)")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "migrate"
    if cmd == "migrate":
        migrate()
    elif cmd == "export":
        export_json(sys.argv[2] if len(sys.argv) > 2 else DEFAULT_EXPORT)
    elif cmd == "list":
        for r in list_uploads():
            print(f"{r['captured_date']}  {r['source']:<14} {r['dataset']:<12} "
                  f"{(r['rows'] or 0):>8,} rows  {(r['bytes'] or 0)/1e6:>7.1f} MB  "
                  f"{r['status']}  {r['filename']}")
    else:
        sys.exit(f"unknown command: {cmd}")
