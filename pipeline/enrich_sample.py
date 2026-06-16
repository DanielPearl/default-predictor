#!/usr/bin/env python3
"""
Enrich properties_sample.json with per-property features from the key-based
PortlandMaps Developer API (bathrooms, zoning, neighborhood, permit activity,
code-enforcement cases). Raw API extracts are cached in data/enrich_cache.json
so re-runs cost zero API calls. Rate limit is 200 requests / 15 min per key.

Run after export_sample.py:  python3 enrich_sample.py
"""
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "properties_sample.json"
CACHE = ROOT / "data" / "enrich_cache.json"
KEY = (ROOT / "Secret Keys" / "portland_maps_api_key.txt").read_text().strip()
API = "https://www.portlandmaps.com/api/"
ENFORCE_RE = re.compile(r"enforce|complian|violation|nuisance|derelict|abate", re.I)


def call(endpoint, params, retries=4):
    params = {**params, "api_key": KEY, "format": "json"}
    url = API + endpoint + "/?" + urllib.parse.urlencode(params)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=40) as r:
                if r.status == 429:
                    raise RuntimeError("429")
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = int(e.headers.get("X-Rate-Limit-Reset", 60)) + 2
                print(f"  rate limited; sleeping {wait}s")
                time.sleep(wait)
                continue
            raise
        except Exception as e:  # noqa: BLE001
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"failed: {endpoint} {params.get('detail_id') or params.get('property_id')}")


def parse_baths(s):
    if not s:
        return None
    full = sum(int(x) for x in re.findall(r"(\d+)\s+FULL", s, re.I))
    half = sum(int(x) for x in re.findall(r"(\d+)\s+HALF", s, re.I))
    total = full + 0.5 * half
    return total or None


def year_of(*dates):
    yrs = [int(m.group()) for d in dates if d for m in [re.search(r"\d{4}", d)] if m]
    return max(yrs) if yrs else None


def fetch(pid):
    detail = call("detail", {"detail_type": "property", "detail_id": pid, "sections": "summary"})
    summary = (detail or {}).get("summary", {}) if detail.get("status") != "error" else {}
    zoning = summary.get("zoning") or []
    permit = call("permit", {"property_id": pid})
    results = permit.get("results") or []
    enforcement = [r for r in results if ENFORCE_RE.search((r.get("type") or "") + " " + (r.get("description") or ""))]
    last_year = year_of(*[r.get("final") or r.get("issued") or r.get("set_up") for r in results])
    return {
        "bathrooms": parse_baths(summary.get("bathrooms")),
        "zoning": zoning[0]["code"] if zoning else "",
        "neighborhood": (summary.get("neighborhood") or "").title(),
        "council_district": summary.get("council_district") or "",
        "permit_count": len(results),
        "last_permit_year": last_year,
        "enforcement_count": len(enforcement),
    }


def main():
    props = json.loads(SAMPLE.read_text())
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    CACHE.parent.mkdir(parents=True, exist_ok=True)

    enforcement_types = set()
    for i, p in enumerate(props, 1):
        pid = p["property_id"]
        if pid not in cache:
            cache[pid] = fetch(pid)
            CACHE.write_text(json.dumps(cache, indent=1))
            print(f"  [{i}/{len(props)}] {pid} -> baths={cache[pid]['bathrooms']} "
                  f"permits={cache[pid]['permit_count']} enforce={cache[pid]['enforcement_count']}")
            time.sleep(0.3)
        p.update(cache[pid])

    SAMPLE.write_text(json.dumps(props, indent=1))
    print(f"\nEnriched {len(props)} properties.")
    print("with enforcement cases:", sum(1 for p in props if p.get("enforcement_count")))


if __name__ == "__main__":
    main()
