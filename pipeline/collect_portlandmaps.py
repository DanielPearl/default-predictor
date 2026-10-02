#!/usr/bin/env python3
"""
Weekly PortlandMaps collector -> data lake.

Pulls the full Multnomah County assessor dataset from the PortlandMaps
Developer API (owner, value, sale, legal description, location for every
account) and lands it raw in the lake as one gzipped NDJSON file per week,
then records a provenance row in the catalog. This is the first source feeding
the lake; others follow the same shape.

    python3 pipeline/collect_portlandmaps.py

Env:
    CAPTURE_DATE        override the snapshot date (default: today, UTC)
    COLLECT_MAX_PAGES   stop after N pages (for a quick test run)
    FORCE=1             re-capture even if this week is already complete
    EXPORT_UPLOADS      also write the site's uploads.json to this path

Rate limit: 200 requests / 15 min. On HTTP 429 we sleep until the window
resets (per the X-Rate-Limit-Reset header) and continue. Stdlib only.
"""
import json
import os
import sys
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
API = "https://www.portlandmaps.com/api/assessor/"
SOURCE = "PortlandMaps"
DATASET = "assessor"
COUNTY = "Multnomah"
PAGE_SIZE = 1000


def fetch_page(page, retries=5):
    params = {"county": COUNTY, "page": page, "api_key": KEY, "format": "json"}
    url = API + "?" + urllib.parse.urlencode(params)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = int(e.headers.get("X-Rate-Limit-Reset", 60)) + 2
                print(f"  rate limited on page {page}; sleeping {wait}s", flush=True)
                time.sleep(wait)
                continue
            raise
        except Exception as e:  # noqa: BLE001  (transient network)
            print(f"  page {page} attempt {attempt + 1} failed: {e}", flush=True)
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"gave up on page {page}")


def already_done(captured_date):
    for r in catalog.list_uploads():
        if (r["source"], r["dataset"], r["captured_date"], r["status"]) == \
           (SOURCE, DATASET, captured_date, "complete"):
            return True
    return False


def main():
    captured_date = os.environ.get("CAPTURE_DATE") or lake.capture_date()
    max_pages = int(os.environ.get("COLLECT_MAX_PAGES", "0")) or None
    catalog.migrate()

    if already_done(captured_date) and os.environ.get("FORCE") != "1":
        print(f"{captured_date}: already captured (set FORCE=1 to redo); skipping")
        return

    filename = f"{DATASET}.ndjson.gz"
    print(f"capturing {SOURCE}/{DATASET} for {captured_date} -> lake", flush=True)
    t0 = time.time()
    total = None
    writer = lake.RawWriter(SOURCE, DATASET, captured_date)
    status = "failed"
    facts = {"relpath": lake.relpath(SOURCE, DATASET, captured_date),
             "rows": 0, "bytes": 0, "sha256": None}
    try:
        page = 1
        while True:
            d = fetch_page(page)
            results = d.get("results") or []
            if total is None:
                total = d.get("total")
                print(f"  total accounts reported: {total:,}", flush=True)
            for rec in results:
                writer.write(rec)
            print(f"  page {page}: +{len(results)} (have {writer.rows:,})", flush=True)
            if len(results) < PAGE_SIZE:
                break
            if total and writer.rows >= total:
                break
            if max_pages and page >= max_pages:
                print(f"  stopping at COLLECT_MAX_PAGES={max_pages}", flush=True)
                break
            page += 1
        facts = writer.close()
        status = "complete" if (not max_pages and (not total or facts["rows"] >= total)) else "partial"
    except Exception as e:  # noqa: BLE001
        writer.__exit__(e, e, None)
        catalog.record_upload(
            source=SOURCE, dataset=DATASET, captured_date=captured_date,
            filename=filename, relpath=facts["relpath"], source_url=API,
            content_type="application/x-ndjson+gzip", rows=writer.rows, bytes=0,
            sha256=None, status="failed",
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            duration_s=round(time.time() - t0, 1), notes=str(e)[:300])
        raise

    dur = round(time.time() - t0, 1)
    catalog.record_upload(
        source=SOURCE, dataset=DATASET, captured_date=captured_date,
        filename=filename, relpath=facts["relpath"], source_url=API,
        content_type="application/x-ndjson+gzip", rows=facts["rows"],
        bytes=facts["bytes"], sha256=facts["sha256"], status=status,
        fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        duration_s=dur,
        notes=f"county={COUNTY}; reported_total={total}")
    lake.write_manifest(SOURCE, captured_date, [{
        "dataset": DATASET, "filename": filename, "relpath": facts["relpath"],
        "rows": facts["rows"], "bytes": facts["bytes"], "sha256": facts["sha256"],
        "status": status}])

    print(f"{status}: {facts['rows']:,} rows, {facts['bytes']/1e6:.1f} MB in {dur}s "
          f"-> {facts['relpath']}", flush=True)

    export = os.environ.get("EXPORT_UPLOADS")
    if export:
        catalog.export_json(export)


if __name__ == "__main__":
    sys.exit(main())
