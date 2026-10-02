#!/usr/bin/env python3
"""
Build a SEPARATE `lake.duckdb` catalog of read-only views over the raw lake
files. The lake is its own database -- distinct from the warehouse -- so the
DuckDB UI shows `lake` and `warehouse` as two top-level entities (raw vs
modeled), not a schema nested inside the warehouse. Uses absolute paths, so it
resolves regardless of the UI's working dir.

    .venv/bin/python pipeline/make_lake_views.py
"""
import glob
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "lake.duckdb"            # the lake is its OWN database
LAKE = (ROOT / "data" / "lake").resolve()

DATASETS = {
    "assessor":         "portlandmaps/*/assessor.ndjson.gz",
    "taxlots":          "portlandmaps/*/taxlots.ndjson.gz",
    "permits":          "portlandmaps/*/permits.ndjson.gz",
    "demolitions":      "portlandmaps/*/demolitions.ndjson.gz",
    "violations":       "portlandmaps/*/violations.ndjson.gz",
    "permit_detail":    "portlandmaps/*/permit_detail.ndjson.gz",
    "rental_portfolio": "portlandmaps/*/rental_portfolio.ndjson.gz",
    "sos_businesses":   "oregon-sos/*/businesses.ndjson.gz",
}


def main():
    con = duckdb.connect(str(DB))
    made = 0
    for name, g in DATASETS.items():
        if not glob.glob(str(LAKE / g)):
            continue  # skip datasets not present in the lake
        con.execute(
            f"CREATE OR REPLACE VIEW {name} AS "
            f"SELECT *, regexp_extract(filename, '[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}') AS captured_date "
            f"FROM read_json_auto('{LAKE}/{g}', filename=true, union_by_name=true, ignore_errors=true)")
        made += 1
    con.close()
    print(f"lake.duckdb: {made} views over raw files at {LAKE}")


if __name__ == "__main__":
    main()
