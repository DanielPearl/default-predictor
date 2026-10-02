#!/usr/bin/env python3
"""
Browse the data lake in the DuckDB UI -- without turning the lake into a database.

The lake is just files in a partitioned store (a local folder today, or a
DigitalOcean Space once Secret Keys/do_spaces.json exists). This opens the
DuckDB web UI over an IN-MEMORY connection whose only object is `lake_files`:
a LIVE directory listing (source, dataset, captured_date, path) built with
glob(). Nothing is stored or materialized -- it shows WHERE the dumps are, not
their contents. To read a file's contents, query it on demand with
read_json_auto(<path>, hive_partitioning=true).

    .venv/bin/python pipeline/browse_lake.py
Then open http://localhost:4213 and click `lake_files`.
"""
import time

import duckdb

import lake

BASE = lake.lake_uri()  # local folder path, or s3://<bucket> when on Spaces

con = duckdb.connect()  # in-memory: a viewer over the store, not a stored DB

cfg = lake.spaces_config()
if cfg:
    # read the Space directly over the network (laptop compute, remote lake)
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute(f"""
        CREATE SECRET spaces (
            TYPE S3, KEY_ID '{cfg["access_key"]}', SECRET '{cfg["secret_key"]}',
            REGION '{cfg["region"]}', ENDPOINT '{cfg["endpoint"].replace("https://", "")}',
            URL_STYLE 'vhost', USE_SSL true)
    """)

con.execute(f"""
    CREATE VIEW lake_files AS
    SELECT regexp_extract(file, '([^/]+)/([^/]+)/captured_date=([0-9-]+)', 1) AS source,
           regexp_extract(file, '([^/]+)/([^/]+)/captured_date=([0-9-]+)', 2) AS dataset,
           regexp_extract(file, 'captured_date=([0-9-]+)', 1)                 AS captured_date,
           regexp_extract(file, '([^/]+/[^/]+/captured_date=[0-9-]+/[^/]+)$', 1) AS path
    FROM glob('{BASE}/**/*.ndjson.gz')
    ORDER BY source, dataset, captured_date
""")
con.execute("CALL start_ui_server()")
print(f"DuckDB UI: http://localhost:4213   (in-memory; view: lake_files; lake: {BASE})")
time.sleep(86400)
