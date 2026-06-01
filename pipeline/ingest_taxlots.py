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
import hashlib
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

# NOTE: the service's OBJECTID is a *volatile* per-query row number (it
# renumbers 1..N for each filtered query), so it is unsafe as a key. We page by
# it (deterministic within a single run) but never store it. The stable key is
# the taxlot id (STATE_ID), with fallbacks for the handful of blank ones.

# Source fields pulled into SQLite. Names match the source so the data
# dictionary (features.csv) maps cleanly. `parcel_key` is our derived PK.
FIELDS = [
    "STATE_ID", "RNO", "PROPERTYID", "TLID",
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
COLUMNS = ["parcel_key"] + FIELDS


def col_type(name):
    if name == "parcel_key":
        return "TEXT PRIMARY KEY"
    return "REAL" if name in REAL_FIELDS else "TEXT"


def parcel_key(a):
    """Stable per-account key. STATE_ID is the taxlot (shared by condos and
    multi-account parcels), so we combine it with PROPERTYID (the account).
    Falls back to other ids, then a full-row hash, so no record is ever lost."""
    sid = (a.get("STATE_ID") or "").strip()
    pid = (a.get("PROPERTYID") or "").strip()
    if sid or pid:
        return sid + "|" + pid
    for f in ("TLID", "RNO"):
        v = (a.get(f) or "").strip()
        if v:
            return "alt:" + v
    blob = json.dumps({f: a.get(f) for f in FIELDS}, sort_keys=True)
    return "HASH:" + hashlib.md5(blob.encode()).hexdigest()


def init_db(conn, fresh):
    if fresh:
        conn.execute("DROP TABLE IF EXISTS taxlots")
    cols = ", ".join(f'"{c}" {col_type(c)}' for c in COLUMNS)
    conn.execute(f"CREATE TABLE IF NOT EXISTS taxlots ({cols})")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_propertyid ON taxlots(PROPERTYID)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_siteaddr ON taxlots(SITEADDR)")
    conn.commit()


def fetch_page(where, offset, retries=4):
    params = {
        "where": where,
        "outFields": ",".join(FIELDS),
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
    placeholders = ", ".join("?" for _ in COLUMNS)
    sql = f'INSERT OR REPLACE INTO taxlots VALUES ({placeholders})'
    rows = []
    for feat in features:
        a = feat.get("attributes", {})
        rows.append((parcel_key(a),) + tuple(a.get(f) for f in FIELDS))
    conn.executemany(sql, rows)
    conn.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--where", default="COUNTY='M'", help="ArcGIS where clause")
    ap.add_argument("--db", default=str(Path(__file__).resolve().parents[1] / "data" / "taxlots.db"))
    ap.add_argument("--max-pages", type=int, default=0, help="0 = all pages")
    ap.add_argument("--sleep", type=float, default=0.3, help="seconds between pages")
    ap.add_argument("--no-fresh", action="store_true",
                    help="keep existing table (default drops and rebuilds)")
    args = ap.parse_args()

    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(args.db)
    init_db(conn, fresh=not args.no_fresh)

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
    print(f"\nDone in {time.time()-t0:.1f}s. Fetched {total} rows; rows in DB: {count}")

    # Coverage check against the live service count (skip when limited/test run).
    if not args.max_pages:
        try:
            svc = urllib.request.urlopen(SERVICE + "?" + urllib.parse.urlencode({
                "where": args.where, "returnCountOnly": "true", "f": "json"}), timeout=30)
            svc_count = json.load(svc).get("count")
            delta = count - svc_count if svc_count is not None else None
            print(f"Service reports {svc_count} matching rows (DB delta: {delta:+d}).")
            if delta == 0:
                print("Coverage OK: DB matches the service exactly.")
            else:
                print("WARNING: DB count does not match the service. Investigate.",
                      file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"(could not verify against service: {e})", file=sys.stderr)
    conn.close()


if __name__ == "__main__":
    main()
