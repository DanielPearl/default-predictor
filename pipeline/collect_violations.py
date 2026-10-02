#!/usr/bin/env python3
"""
Per-property violations (+ permit detail) backfill -> data lake.

There is no bulk source for code-enforcement cases, so this iterates each
residential property through the PortlandMaps keyed `permit` endpoint (which
returns that property's permits AND code cases), caches the raw response, and
flushes two consolidated lake files:
  - violations.ndjson.gz    (the code-enforcement cases -- the distress signal)
  - permit_detail.ndjson.gz (the other permit records, captured free)

~10 days for residential at the 200-req/15-min limit. RESUMABLE: every
property's response is cached in data/violations_cache.db, so a restart skips
what's already done. Safe to stop/start.

  python3 pipeline/collect_violations.py          # full residential backfill
  LIMIT=50 python3 pipeline/collect_violations.py  # quick test

Env: LIMIT, FLUSH_EVERY (default 5000), CAPTURE_DATE, EXPORT_UPLOADS.
Stdlib only.
"""
import json
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import catalog
import lake

ROOT = Path(__file__).resolve().parents[1]
KEY = (ROOT / "Secret Keys" / "portland_maps_api_key.txt").read_text().strip()
API = "https://www.portlandmaps.com/api/"
TAXLOTS = ROOT / "data" / "taxlots.db"
CACHE = ROOT / "data" / "violations_cache.db"
SOURCE = "PortlandMaps"

# A permit-endpoint record is a code-enforcement case (vs a building permit) if
# its type/work marks it as enforcement. Mirrors enrich_sample.py.
ENFORCE_TYPES = {"Vacant", "Occupied Building", "Other- NU", "Zoning", "Motor Vehicle",
                 "Complaint", "Summary Abatement", "Nuisance", "Property Maintenance",
                 "Derelict", "Dangerous Building", "Sign"}
ENFORCE_WORK = {"Complaint", "Inspector Initiated"}


def is_enforcement(r):
    return (r.get("type") in ENFORCE_TYPES) or (r.get("work") in ENFORCE_WORK)


def call(params, retries=5):
    params = {**params, "api_key": KEY, "format": "json"}
    url = API + "permit/?" + urllib.parse.urlencode(params)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=40) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = int(e.headers.get("X-Rate-Limit-Reset", 60)) + 2
                print(f"  rate limited; sleeping {wait}s", flush=True)
                time.sleep(wait)
                continue
            if e.code == 404:
                return {"results": []}   # no record for this property
            return None
        except Exception:  # noqa: BLE001  (transient)
            time.sleep(2 * (attempt + 1))
    return None  # give up -> leave uncached so it retries next run


def cache_conn():
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(CACHE, timeout=60)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE IF NOT EXISTS cache "
              "(property_id TEXT PRIMARY KEY, fetched_at TEXT, records TEXT)")
    return c


def residential_ids():
    c = sqlite3.connect(TAXLOTS)
    ids = [r[0] for r in c.execute(
        "SELECT DISTINCT PROPERTYID FROM taxlots "
        "WHERE PRPCD_DESC LIKE 'RESID%' AND PROPERTYID IS NOT NULL AND PROPERTYID<>''")]
    c.close()
    return ids


def flush_to_lake(captured_date, status):
    """Rebuild the consolidated violations + permit_detail lake files from the
    cache (idempotent; grows as the cache fills)."""
    cc = cache_conn()
    vw = lake.RawWriter(SOURCE, "violations", captured_date)
    pw = lake.RawWriter(SOURCE, "permit_detail", captured_date)
    nprop = 0
    for pid, rec_json in cc.execute("SELECT property_id, records FROM cache"):
        nprop += 1
        for rec in json.loads(rec_json):
            rec = {**rec, "property_id": pid}
            (vw if is_enforcement(rec) else pw).write(rec)
    vf, pf = vw.close(), pw.close()
    cc.close()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for ds, f, fn in (("violations", vf, "violations.ndjson.gz"),
                      ("permit_detail", pf, "permit_detail.ndjson.gz")):
        catalog.record_upload(
            source=SOURCE, dataset=ds, captured_date=captured_date, filename=fn,
            relpath=f["relpath"], source_url=API + "permit/",
            content_type="application/x-ndjson+gzip", rows=f["rows"], bytes=f["bytes"],
            sha256=f["sha256"], status=status, fetched_at=now, duration_s=None,
            notes=f"per-property backfill; {nprop:,} properties cached")
    lake.write_manifest(SOURCE, captured_date, [
        {"dataset": "violations", "filename": "violations.ndjson.gz",
         "relpath": vf["relpath"], "rows": vf["rows"], "bytes": vf["bytes"], "status": status},
        {"dataset": "permit_detail", "filename": "permit_detail.ndjson.gz",
         "relpath": pf["relpath"], "rows": pf["rows"], "bytes": pf["bytes"], "status": status}])
    return vf["rows"], pf["rows"], nprop


def main():
    captured_date = os.environ.get("CAPTURE_DATE") or lake.capture_date()
    limit = int(os.environ.get("LIMIT", "0")) or None
    flush_every = int(os.environ.get("FLUSH_EVERY", "5000"))
    catalog.migrate()

    cc = cache_conn()
    done = {r[0] for r in cc.execute("SELECT property_id FROM cache")}
    cc.close()
    ids = residential_ids()
    todo = [p for p in ids if p not in done]
    if limit:
        todo = todo[:limit]
    print(f"residential: {len(ids):,}  cached: {len(done):,}  to do: {len(todo):,}", flush=True)

    cc = cache_conn()
    new = 0
    for pid in todo:
        d = call({"property_id": pid})
        if d is None:
            continue  # gave up on this one; retry next run
        recs = d.get("results") or []
        cc.execute("INSERT OR REPLACE INTO cache (property_id, fetched_at, records) VALUES (?,?,?)",
                   (pid, datetime.now(timezone.utc).isoformat(timespec="seconds"), json.dumps(recs)))
        cc.commit()
        new += 1
        if new % 200 == 0:
            print(f"  {new:,}/{len(todo):,} fetched", flush=True)
        if new % flush_every == 0:
            v, p, n = flush_to_lake(captured_date, "partial")
            print(f"  flushed: {v:,} violations, {p:,} permits from {n:,} properties", flush=True)
    cc.close()

    complete = (not limit) and (len(done) + new) >= len(ids)
    v, p, n = flush_to_lake(captured_date, "complete" if complete else "partial")
    export = os.environ.get("EXPORT_UPLOADS")
    if export:
        catalog.export_json(export)
    print(f"done: {v:,} violations, {p:,} permit records from {n:,} properties "
          f"({'complete' if complete else 'partial'})", flush=True)


if __name__ == "__main__":
    main()
