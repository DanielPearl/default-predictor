#!/usr/bin/env python3
"""
Weekly bulk collectors for PortlandMaps open-data ArcGIS layers -> data lake.

These layers are keyless and have no rate limit, so the whole layer is pulled
each week and landed raw as gzipped NDJSON (one object per feature's
attributes), cataloged exactly like the assessor capture. One generic
paginator drives every dataset in the registry below.

    python3 pipeline/collect_arcgis.py                 # all datasets
    python3 pipeline/collect_arcgis.py permits taxlots # a subset

Env: CAPTURE_DATE, EXPORT_UPLOADS (same meaning as collect_portlandmaps.py).
Stdlib only.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import catalog
import lake

SOURCE = "PortlandMaps"
OD = "https://www.portlandmaps.com/od/rest/services"

DATASETS = {
    "permits": {
        "dataset": "permits",
        "url": f"{OD}/COP_OpenData_PlanningDevelopment/MapServer/89/query",
        "where": "1=1", "page_size": 2000,
        "about": "Residential building permits",
    },
    "demolitions": {
        "dataset": "demolitions",
        "url": f"{OD}/COP_OpenData_PlanningDevelopment/MapServer/126/query",
        "where": "1=1", "page_size": 2000,
        "about": "Residential demolition permits",
    },
    "taxlots": {
        "dataset": "taxlots",
        "url": "https://www.portlandmaps.com/arcgis/rest/services/Public/Taxlots/MapServer/0/query",
        "where": "COUNTY='M'", "page_size": 4000,
        "about": "Multnomah taxlots (parcel attributes)",
    },
}


def _get(url, params, retries=4, timeout=120):
    full = url + "?" + urllib.parse.urlencode(params)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(full, timeout=timeout) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001  (transient network)
            print(f"  retry {attempt + 1}: {e}", flush=True)
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"failed: {url} {params.get('resultOffset')}")


def count(url, where):
    return _get(url, {"where": where, "returnCountOnly": "true", "f": "json"},
                timeout=60).get("count")


def collect(cfg, captured_date):
    dataset, url, where, ps = cfg["dataset"], cfg["url"], cfg["where"], cfg["page_size"]
    filename = f"{dataset}.ndjson.gz"
    print(f"capturing {SOURCE}/{dataset} -> lake", flush=True)
    t0 = time.time()
    total = count(url, where)
    print(f"  reported count: {total:,}", flush=True)

    writer = lake.RawWriter(SOURCE, dataset, captured_date, filename)
    facts = {"relpath": lake.relpath(SOURCE, captured_date, filename),
             "rows": 0, "bytes": 0, "sha256": None}
    status = "failed"
    try:
        offset = 0
        while True:
            d = _get(url, {"where": where, "outFields": "*", "returnGeometry": "false",
                           "resultOffset": offset, "resultRecordCount": ps, "f": "json"})
            feats = d.get("features", [])
            for ft in feats:
                writer.write(ft.get("attributes", {}))
            print(f"  offset {offset}: +{len(feats)} (have {writer.rows:,})", flush=True)
            offset += len(feats)          # advance by actual count (service may cap below ps)
            if not feats or not d.get("exceededTransferLimit"):
                break
        facts = writer.close()
        status = "complete"
    except Exception as e:  # noqa: BLE001
        writer.__exit__(e, e, None)
        catalog.record_upload(
            source=SOURCE, dataset=dataset, captured_date=captured_date,
            filename=filename, relpath=facts["relpath"], source_url=url,
            content_type="application/x-ndjson+gzip", rows=writer.rows, bytes=0,
            sha256=None, status="failed",
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            duration_s=round(time.time() - t0, 1), notes=str(e)[:300])
        raise

    dur = round(time.time() - t0, 1)
    catalog.record_upload(
        source=SOURCE, dataset=dataset, captured_date=captured_date,
        filename=filename, relpath=facts["relpath"], source_url=url,
        content_type="application/x-ndjson+gzip", rows=facts["rows"],
        bytes=facts["bytes"], sha256=facts["sha256"], status=status,
        fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        duration_s=dur, notes=f"{cfg['about']}; where={where}; reported_total={total}")
    lake.write_manifest(SOURCE, captured_date, [{
        "dataset": dataset, "filename": filename, "relpath": facts["relpath"],
        "rows": facts["rows"], "bytes": facts["bytes"], "sha256": facts["sha256"],
        "status": status}])
    print(f"{status}: {facts['rows']:,} rows, {facts['bytes']/1e6:.1f} MB in {dur}s "
          f"-> {facts['relpath']}", flush=True)


def main():
    captured_date = os.environ.get("CAPTURE_DATE") or lake.capture_date()
    catalog.migrate()
    keys = sys.argv[1:] or list(DATASETS)
    for k in keys:
        if k not in DATASETS:
            print(f"unknown dataset: {k} (have: {', '.join(DATASETS)})")
            continue
        collect(DATASETS[k], captured_date)
    export = os.environ.get("EXPORT_UPLOADS")
    if export:
        catalog.export_json(export)


if __name__ == "__main__":
    main()
