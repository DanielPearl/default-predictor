#!/usr/bin/env python3
"""
Ingest Multnomah County taxlots from the keyless PortlandMaps ArcGIS REST
service into a local SQLite database. This is the property base everything
else joins onto.

No API key and no third-party packages required (stdlib only).

Usage:
    python3 ingest_taxlots.py                 # full Multnomah ingest
    python3 ingest_taxlots.py --max-pages 1   # quick test (one page)
    python3 ingest_taxlots.py --where "COUNTY='M' AND PRPCD_DESC LIKE 'RESID%'"
"""
import argparse
import json
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

SERVICE = ("https://www.portlandmaps.com/arcgis/rest/services"
           "/Public/Taxlots/MapServer/0/query")
PAGE_SIZE = 4000  # service maxRecordCount

# Fields pulled from the layer -> SQLite columns. Keep names identical to the
# source so the data dictionary (features.csv) maps cleanly.
FIELDS = [
    "OBJECTID", "STATE_ID", "RNO", "PROPERTYID", "TLID",
    "OWNER1", "OWNER2", "OWNER3",
    "OWNERADDR", "OWNERCITY", "OWNERSTATE", "OWNERZIP",
    "SITEADDR", "SITECITY", "SITEZIP",
    "LEGAL_DESC", "TAXCODE", "PROP_CODE", "PRPCD_DESC", "LANDUSE",
    "YEARBUILT", "BLDGSQFT", "BEDROOMS", "FLOORS", "UNITS",
    "LANDVAL1", "BLDGVAL1", "TOTALVAL1", "MKTVALYR1",
    "TOTALVAL2", "MKTVALYR2", "TOTALVAL3", "MKTVALYR3",
    "SALEDATE", "SALEPRICE", "ACC_STATUS",
    "A_T_SQFT", "A_T_ACRES", "FRONTAGE", "COUNTY",
]
REAL_FIELDS = {
    "BLDGSQFT", "BEDROOMS", "FLOORS", "UNITS",
    "LANDVAL1", "BLDGVAL1", "TOTALVAL1",
    "TOTALVAL2", "TOTALVAL3", "SALEPRICE",
    "A_T_SQFT", "A_T_ACRES", "FRONTAGE",
}


def col_type(name):
    if name == "OBJECTID":
        return "INTEGER PRIMARY KEY"
    return "REAL" if name in REAL_FIELDS else "TEXT"


def init_db(conn):
    cols = ", ".join(f'"{f}" {col_type(f)}' for f in FIELDS)
    conn.execute(f"CREATE TABLE IF NOT EXISTS taxlots ({cols})")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_propertyid ON taxlots(PROPERTYID)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_siteaddr ON taxlots(SITEADDR)")
    conn.commit()


def fetch_page(where, offset, retries=4):
    params = {
        "where": where,
        "outFields": ",".join(f for f in FIELDS if f != "OBJECTID"),
        "returnGeometry": "false",
        "orderByFields": "OBJECTID",
        "resultOffset": offset,
        "resultRecordCount": PAGE_SIZE,
        "f": "json",
    }
    data = urllib.parse.urlencode(params).encode()
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(SERVICE, data=data)
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = json.load(resp)
            if "error" in payload:
                raise RuntimeError(payload["error"])
            return payload.get("features", []), payload.get("exceededTransferLimit", False)
        except Exception as e:  # noqa: BLE001
            last_err = e
            wait = 2 * (attempt + 1)
            print(f"  ! page offset={offset} attempt {attempt+1} failed: {e}; retrying in {wait}s",
                  file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"giving up on offset {offset}: {last_err}")


def upsert(conn, features):
    placeholders = ", ".join("?" for _ in FIELDS)
    sql = f'INSERT OR REPLACE INTO taxlots VALUES ({placeholders})'
    rows = []
    for feat in features:
        a = feat.get("attributes", {})
        rows.append(tuple(a.get(f) for f in FIELDS))
    conn.executemany(sql, rows)
    conn.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--where", default="COUNTY='M'", help="ArcGIS where clause")
    ap.add_argument("--db", default=str(Path(__file__).resolve().parents[1] / "data" / "taxlots.db"))
    ap.add_argument("--max-pages", type=int, default=0, help="0 = all pages")
    ap.add_argument("--sleep", type=float, default=0.3, help="seconds between pages")
    args = ap.parse_args()

    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(args.db)
    init_db(conn)

    print(f"DB: {args.db}")
    print(f"WHERE: {args.where}")
    offset, page, total = 0, 0, 0
    t0 = time.time()
    while True:
        features, more = fetch_page(args.where, offset)
        if not features:
            break
        upsert(conn, features)
        total += len(features)
        page += 1
        print(f"  page {page}: +{len(features)} rows (total {total})")
        if args.max_pages and page >= args.max_pages:
            print(f"stopping at max-pages={args.max_pages}")
            break
        if len(features) < PAGE_SIZE and not more:
            break
        offset += PAGE_SIZE
        time.sleep(args.sleep)

    count = conn.execute("SELECT COUNT(*) FROM taxlots").fetchone()[0]
    print(f"\nDone in {time.time()-t0:.1f}s. Rows in DB: {count}")
    conn.close()


if __name__ == "__main__":
    main()
