#!/usr/bin/env python3
"""
Build the lake's Parquet (silver) layer from the raw NDJSON (bronze).

Bronze = <source>/<dataset>/captured_date=*/<ds>.ndjson.gz  (append-only, raw).
Silver = parquet/<source>/<dataset>/captured_date=*/*.parquet (columnar).

dbt staging reads the silver layer. Parquet reads -- especially from Spaces/S3 --
are far faster than scanning gzipped JSON (columnar, projection + row-group
pushdown, no JSON parse): ~20x on this lake.

Reads from and writes to the lake wherever it lives: the local folder, or
DigitalOcean Spaces (s3://) when Secret Keys/do_spaces.json is present. Re-run
after new captures (optionally for a single dataset: `... permits`).

    python3 pipeline/lake_to_parquet.py            # all datasets
    python3 pipeline/lake_to_parquet.py permits    # just one
"""
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lake  # noqa: E402

# (source, dataset) pairs the collectors land in the lake.
DATASETS = [
    ("portlandmaps", "taxlots"), ("portlandmaps", "assessor"),
    ("portlandmaps", "permits"), ("portlandmaps", "demolitions"),
    ("portlandmaps", "rental_portfolio"), ("portlandmaps", "violations"),
    ("portlandmaps", "permit_detail"), ("oregon-sos", "businesses"),
    ("pacer-d-oregon", "bankruptcy"),
]


def _connect():
    con = duckdb.connect()
    cfg = lake.spaces_config()
    if cfg:
        con.execute("INSTALL httpfs")
        con.execute("LOAD httpfs")
        endpoint = cfg["endpoint"].replace("https://", "").replace("http://", "")
        con.execute(
            "CREATE SECRET (TYPE s3, KEY_ID ?, SECRET ?, REGION ?, ENDPOINT ?, URL_STYLE 'vhost')",
            [cfg["access_key"], cfg["secret_key"], cfg["region"], endpoint])
    return con


def main(only=None):
    base = lake.lake_uri()  # local path or s3://bucket
    con = _connect()
    print(f"lake: {base}")
    for src, ds in DATASETS:
        if only and ds != only:
            continue
        srcglob = f"{base}/{src}/{ds}/captured_date=*/*.ndjson.gz"
        out = f"{base}/parquet/{src}/{ds}"
        try:
            if not base.startswith("s3://"):
                Path(out).mkdir(parents=True, exist_ok=True)
            con.execute(f"""
                COPY (SELECT * FROM read_json_auto('{srcglob}',
                           hive_partitioning=true, union_by_name=true, ignore_errors=true))
                TO '{out}' (FORMAT parquet, PARTITION_BY (captured_date), OVERWRITE_OR_IGNORE 1)
            """)
            n = con.execute(
                f"SELECT count(*) FROM read_parquet('{out}/captured_date=*/*.parquet', "
                "hive_partitioning=true)").fetchone()[0]
            print(f"  {src}/{ds}: {n} rows -> parquet")
        except Exception as e:  # noqa: BLE001  (no data yet for this dataset, etc.)
            print(f"  {src}/{ds}: skipped ({str(e).splitlines()[0]})")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
