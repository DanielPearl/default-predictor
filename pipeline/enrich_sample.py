#!/usr/bin/env python3
"""
Enrich properties_sample.json with per-property features from the key-based
PortlandMaps Developer API (detail sections=* + permit). RAW responses are
cached in data/enrich_cache.json so extraction is re-runnable with zero API
calls; only un-cached properties hit the network. Rate limit 200 req / 15 min.

Run after export_sample.py:  python3 enrich_sample.py
"""
import json
import math
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
# The permit endpoint mixes building permits with code-enforcement cases. A
# record is a code case if its type is a known enforcement type or its "work"
# marks it complaint/inspector-initiated.
ENFORCE_TYPES = {"Vacant", "Occupied Building", "Other- NU", "Zoning", "Motor Vehicle",
                 "Complaint", "Summary Abatement", "Nuisance", "Property Maintenance",
                 "Derelict", "Dangerous Building", "Sign"}
ENFORCE_WORK = {"Complaint", "Inspector Initiated"}

def is_enforcement(r):
    return (r.get("type") in ENFORCE_TYPES) or (r.get("work") in ENFORCE_WORK)

# Binary violation types, classified from the case text. The bureaucratic
# `type` field is unreliable, so we read type + work + description.
VIOLATION_RULES = {
    "violation_vacant":     ["vacant", "abate", "securing", "derelict", "dangerous", "boarded", "rodent"],
    "violation_overgrowth": ["overgrown", "tall grass", "weed", "vegetation", "blackberr"],
    "violation_trash":      ["trash", "debris", "garbage", "junk", "rubbish"],
    "violation_vehicle":    ["vehicle", "trailer", "boat", "flat tire", "unpaved", "muffler"],
    "violation_zoning":     ["zoning"],
    "violation_noise":      ["noise", "stereo", "loud"],
}
TYPE_TO_VIOLATION = {"Vacant": "violation_vacant", "Summary Abatement": "violation_vacant",
                     "Zoning": "violation_zoning", "Motor Vehicle": "violation_vehicle"}

def classify_violations(records):
    counts = {k: 0 for k in VIOLATION_RULES}
    for r in records:
        text = " ".join([r.get("type") or "", r.get("work") or "", r.get("description") or ""]).lower()
        matched = set()
        if r.get("type") in TYPE_TO_VIOLATION:
            matched.add(TYPE_TO_VIOLATION[r["type"]])
        for cat, kws in VIOLATION_RULES.items():
            if any(k in text for k in kws):
                matched.add(cat)
        for cat in matched:
            counts[cat] += 1
    return counts
MERCATOR = 20037508.342789244


def call(endpoint, params, retries=4):
    params = {**params, "api_key": KEY, "format": "json"}
    url = API + endpoint + "/?" + urllib.parse.urlencode(params)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=40) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = int(e.headers.get("X-Rate-Limit-Reset", 60)) + 2
                print(f"  rate limited; sleeping {wait}s")
                time.sleep(wait)
                continue
            raise
        except Exception:  # noqa: BLE001
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"failed: {endpoint} {params.get('detail_id') or params.get('property_id')}")


def fetch_raw(pid):
    return {
        "detail": call("detail", {"detail_type": "property", "detail_id": pid, "sections": "*"}),
        "permit": call("permit", {"property_id": pid}),
    }


# ---- pure extraction from raw cache (no network) ----
def parse_baths(s):
    if not s:
        return None
    full = sum(int(x) for x in re.findall(r"(\d+)\s+FULL", s, re.I))
    half = sum(int(x) for x in re.findall(r"(\d+)\s+HALF", s, re.I))
    return (full + 0.5 * half) or None


def year_of(*dates):
    yrs = [int(m.group()) for d in dates if d for m in [re.search(r"\d{4}", d)] if m]
    return max(yrs) if yrs else None


def centroid_latlon(geometry):
    rings = (geometry or {}).get("rings") or []
    if not rings or not rings[0]:
        return None, None
    pts = rings[0]
    x = sum(p[0] for p in pts) / len(pts)
    y = sum(p[1] for p in pts) / len(pts)
    lon = x / MERCATOR * 180
    lat = y / MERCATOR * 180
    lat = 180 / math.pi * (2 * math.atan(math.exp(lat * math.pi / 180)) - math.pi / 2)
    return round(lat, 6), round(lon, 6)


def crime_total(crime):
    data = (crime or {}).get("data") or {}
    total = 0
    for cat in data.values():
        for g in (cat.get("groups") or []):
            try:
                total += float(g.get("value") or 0)
            except (TypeError, ValueError):
                pass
    return int(total) if data else None


def extract(raw):
    detail = raw.get("detail") or {}
    summary = detail.get("summary", {}) if detail.get("status") != "error" else {}
    ps = detail.get("public-safety", {})
    hz = ps.get("hazard", {}) or {}
    zoning = summary.get("zoning") or []
    zcode = zoning[0]["code"] if zoning else ""
    lat, lon = centroid_latlon(detail.get("geometry"))
    results = (raw.get("permit") or {}).get("results") or []
    enforcement = [r for r in results if is_enforcement(r)]
    vflags = classify_violations(enforcement)
    last_year = year_of(*[r.get("final") or r.get("issued") or r.get("set_up") for r in results])
    fire = (ps.get("fire_nearest") or [{}])[0]
    park = (detail.get("parks", {}).get("nearby") or [{}])[0]
    sch = detail.get("schools", {}).get("attendance", {}) or {}
    liq = hz.get("liquefaction_hazard_zone") or ""
    hazard_flags = [
        hz.get("fema_special_flood_hazard_area"),
        hz.get("title_33_potential_landslide_hazard_area"),
        hz.get("steep_slope_area"),
        hz.get("wild_lands_fire_hazard_area"),
        hz.get("1996_flood_inundation_area"),
        liq in ("High", "Very High"),
    ]
    return {
        "bathrooms": parse_baths(summary.get("bathrooms")),
        "zoning": zcode,
        "commercial_zone": "Yes" if zcode[:1] in ("C", "E", "I") else "No",
        "neighborhood": (summary.get("neighborhood") or "").title(),
        "council_district": summary.get("council_district") or "",
        "elevation_ft": summary.get("elevation"),
        "urban_service": "In" if summary.get("urban_service_boundary") else "Out",
        "related_accounts": len(summary.get("related_accounts") or []),
        "account_status": summary.get("account_status_code") or "",
        "latitude": lat,
        "longitude": lon,
        "flood_zone": "Yes" if hz.get("fema_special_flood_hazard_area") else "No",
        "landslide": "Yes" if hz.get("title_33_potential_landslide_hazard_area") else "No",
        "liquefaction": liq,
        "steep_slope": "Yes" if hz.get("steep_slope_area") else "No",
        "hazard_count": sum(1 for f in hazard_flags if f),
        "crime_area": crime_total(ps.get("crime")),
        "fire_dist_ft": round(fire["near_distance"]) if fire.get("near_distance") else None,
        "nearest_park": (park.get("name") or ""),
        "elementary_school": sch.get("elementary_school") or "",
        "school_district": sch.get("district_name") or "",
        "permit_count": len(results),
        "last_permit_year": last_year,
        "years_since_permit": (2026 - last_year) if last_year else None,
        "enforcement_count": len(enforcement),
        **vflags,
    }


def main():
    props = json.loads(SAMPLE.read_text())
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    CACHE.parent.mkdir(parents=True, exist_ok=True)

    for i, p in enumerate(props, 1):
        pid = p["property_id"]
        if pid not in cache or "detail" not in cache.get(pid, {}):
            cache[pid] = fetch_raw(pid)
            CACHE.write_text(json.dumps(cache))
            time.sleep(0.3)
            print(f"  [{i}/{len(props)}] fetched {pid}")
        p.update(extract(cache[pid]))

    SAMPLE.write_text(json.dumps(props, indent=1))
    print(f"\nEnriched {len(props)} properties.")
    print("flood-zone:", sum(1 for p in props if p.get("flood_zone") == "Yes"))
    print("with hazards:", sum(1 for p in props if p.get("hazard_count")))
    print("with enforcement:", sum(1 for p in props if p.get("enforcement_count")))


if __name__ == "__main__":
    main()
