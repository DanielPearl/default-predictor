#!/usr/bin/env python3
"""
Browse the data lake in the DuckDB UI -- without turning the lake into a database.

The lake is just a folder of files (data/lake/). This opens the DuckDB web UI
over an IN-MEMORY connection whose only object is `lake_files`: a LIVE directory
listing (source, dataset, captured_date, path) built from the folder with
glob(). Nothing is stored or materialized -- it shows WHERE the dumps are, not
their contents. Close it and nothing persists. To read a file's contents,
query it on demand with read_json_auto('data/lake/.../*.ndjson.gz',
hive_partitioning=true).

    .venv/bin/python pipeline/browse_lake.py
Then open http://localhost:4213 and click `lake_files`.
"""
import time
from pathlib import Path

import duckdb

LAKE = (Path(__file__).resolve().parents[1] / "data" / "lake").resolve()

con = duckdb.connect()  # in-memory: a viewer over the folder, not a stored DB
con.execute(f"""
    CREATE VIEW lake_files AS
    SELECT regexp_extract(file, 'lake/([^/]+)/', 1)           AS source,
           regexp_extract(file, 'lake/[^/]+/([^/]+)/', 1)     AS dataset,
           regexp_extract(file, 'captured_date=([0-9-]+)', 1) AS captured_date,
           replace(file, '{LAKE}/', '')                       AS path
    FROM glob('{LAKE}/**/*.ndjson.gz')
    ORDER BY source, dataset, captured_date
""")
con.execute("CALL start_ui_server()")
print("DuckDB UI: http://localhost:4213   (in-memory; view: lake_files)")
time.sleep(86400)
