#!/usr/bin/env python3
"""
Oregon Secretary of State "Active Businesses" registry -> data lake.

Bulk Socrata pull (data.oregon.gov, dataset tckn-sxa6): one row per business
associated-name record -- registry number, business name, entity type,
registration date, and address by role (PRINCIPAL PLACE OF BUSINESS /
REGISTERED AGENT / MAILING ADDRESS / AUTHORIZED REPRESENTATIVE).

Use: verify entity owners -- active-vs-dissolved status (a dissolved entity on
a home is a distress signal) and registered addresses to cross-check against
owner mailing addresses. NOTE: the bulk data carries agent/representative
ADDRESSES, not their names (names live only on the gated detail pages).

  python3 pipeline/collect_oregon_sos.py
Env: LIMIT, PAGE (test), CAPTURE_DATE, EXPORT_UPLOADS. Stdlib only.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import catalog
import lake

SOURCE, DATASET = "Oregon SoS", "businesses"
RES = "https://data.oregon.gov/resource/tckn-sxa6.json"


def fetch(offset, page, retries=6):
    params = {"$limit": page, "$offset": offset, "$order": "registry_number"}
    url = RES + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    for a in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = int(e.headers.get("Retry-After", 30)) + 2
                print(f"  throttled; waiting {wait}s", flush=True)
                time.sleep(wait)
                continue
            raise
        except Exception as e:  # noqa: BLE001
            print(f"  retry {a + 1}: {e}", flush=True)
            time.sleep(3 * (a + 1))
    raise RuntimeError(f"failed at offset {offset}")


def main():
    captured_date = os.environ.get("CAPTURE_DATE") or lake.capture_date()
    limit = int(os.environ.get("LIMIT", "0")) or None
    page = int(os.environ.get("PAGE", "50000"))
    catalog.migrate()
    filename = f"{DATASET}.ndjson.gz"
    print(f"capturing {SOURCE}/{DATASET} -> lake", flush=True)
    t0 = time.time()
    writer = lake.RawWriter(SOURCE, DATASET, captured_date, filename)
    status = "failed"
    facts = {"relpath": lake.relpath(SOURCE, captured_date, filename),
             "rows": 0, "bytes": 0, "sha256": None}
    try:
        offset = 0
        while True:
            rows = fetch(offset, page)
            for rec in rows:
                writer.write(rec)
            print(f"  offset {offset}: +{len(rows)} (have {writer.rows:,})", flush=True)
            offset += len(rows)
            if len(rows) < page:
                break
            if limit and writer.rows >= limit:
                break
        facts = writer.close()
        status = "complete" if not limit else "partial"
    except Exception as e:  # noqa: BLE001
        writer.__exit__(e, e, None)
        catalog.record_upload(
            source=SOURCE, dataset=DATASET, captured_date=captured_date, filename=filename,
            relpath=facts["relpath"], source_url=RES, content_type="application/x-ndjson+gzip",
            rows=writer.rows, bytes=0, sha256=None, status="failed",
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            duration_s=round(time.time() - t0, 1), notes=str(e)[:300])
        raise

    dur = round(time.time() - t0, 1)
    catalog.record_upload(
        source=SOURCE, dataset=DATASET, captured_date=captured_date, filename=filename,
        relpath=facts["relpath"], source_url=RES, content_type="application/x-ndjson+gzip",
        rows=facts["rows"], bytes=facts["bytes"], sha256=facts["sha256"], status=status,
        fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), duration_s=dur,
        notes="Oregon SoS Active Businesses; address by role (agent names not in bulk)")
    lake.write_manifest(SOURCE, captured_date, [{
        "dataset": DATASET, "filename": filename, "relpath": facts["relpath"],
        "rows": facts["rows"], "bytes": facts["bytes"], "sha256": facts["sha256"], "status": status}])
    print(f"{status}: {facts['rows']:,} rows, {facts['bytes']/1e6:.1f} MB in {dur}s "
          f"-> {facts['relpath']}", flush=True)
    export = os.environ.get("EXPORT_UPLOADS")
    if export:
        catalog.export_json(export)


if __name__ == "__main__":
    main()
