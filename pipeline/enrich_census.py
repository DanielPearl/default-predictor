#!/usr/bin/env python3
"""
Add Census ACS tract-level socioeconomic context to properties_sample.json.
For each property we geocode its lat/long to a census tract (free Census
geocoder, no key), then pull ACS 5-year estimates per tract (free Census API,
no key for our volume): median income, poverty rate, homeownership rate,
vacancy rate, and median home value.

Run after enrich_bankruptcy.py.
"""
import json
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "properties_sample.json"
CACHE = ROOT / "data" / "census_cache.json"
KEY_FILE = ROOT / "Secret Keys" / "census_bureau_api_key.txt"
GEOCODER = "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"
ACS = "https://api.census.gov/data/2022/acs/acs5"
KEY = KEY_FILE.read_text().strip() if KEY_FILE.exists() else ""
VARS = ["B19013_001E", "B17001_001E", "B17001_002E", "B25003_001E", "B25003_002E",
        "B25002_001E", "B25002_003E", "B25077_001E"]


def get(url, retries=4):
    """The Census geocoder intermittently returns non-JSON; retry with backoff."""
    import time
    last = None
    for attempt in range(retries):
        try:
            return json.load(urllib.request.urlopen(url, timeout=30))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(3 * (attempt + 1))
    raise last


FCC = "https://geo.fcc.gov/api/census/area"


def tract_of(lat, lon):
    """FCC area API first (works from datacenter IPs; the Census geocoder
    blocks them), Census geocoder as fallback. Returns (state, county, tract)."""
    try:
        res = get(FCC + "?" + urllib.parse.urlencode({"lat": lat, "lon": lon, "format": "json"}))
        fips = (res.get("results") or [{}])[0].get("block_fips") or ""
        if len(fips) >= 11:
            return (fips[0:2], fips[2:5], fips[5:11])
    except Exception as e:  # noqa: BLE001
        print(f"  FCC lookup failed for {lat},{lon}: {e}")
    q = urllib.parse.urlencode({"x": lon, "y": lat, "benchmark": "Public_AR_Current",
                                "vintage": "Current_Current", "layers": "Census Tracts",
                                "format": "json"})
    try:
        geos = get(GEOCODER + "?" + q).get("result", {}).get("geographies", {})
    except Exception as e:  # noqa: BLE001 - a flaky geocoder must not kill the run
        print(f"  geocoder failed for {lat},{lon}: {e}; skipping")
        return None
    t = (geos.get("Census Tracts") or [{}])[0]
    return (t.get("STATE"), t.get("COUNTY"), t.get("TRACT")) if t.get("TRACT") else None


def acs(state, county, tract):
    params = {"get": ",".join(VARS), "for": f"tract:{tract}", "in": f"state:{state} county:{county}"}
    if KEY:
        params["key"] = KEY
    rows = get(ACS + "?" + urllib.parse.urlencode(params, safe=":"))
    d = dict(zip(rows[0], rows[1]))
    num = lambda k: float(d[k]) if d.get(k) not in (None, "") and float(d[k]) > -1e6 else None
    pov_t, pov_b = num("B17001_001E"), num("B17001_002E")
    occ_t, occ_o = num("B25003_001E"), num("B25003_002E")
    unit_t, unit_v = num("B25002_001E"), num("B25002_003E")
    pct = lambda a, b: round(a / b * 100, 1) if a is not None and b else None
    return {
        "tract_median_income": int(num("B19013_001E")) if num("B19013_001E") else None,
        "tract_poverty_pct": pct(pov_b, pov_t),
        "tract_homeownership_pct": pct(occ_o, occ_t),
        "tract_vacancy_pct": pct(unit_v, unit_t),
        "tract_median_home_value": int(num("B25077_001E")) if num("B25077_001E") else None,
    }


def main():
    if not KEY:
        print("No Census API key. Sign up (free, instant) at "
              "https://api.census.gov/data/key_signup.html and save it to "
              f"{KEY_FILE}")
        return
    props = json.loads(SAMPLE.read_text())
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    tract_data = {}
    for p in props:
        lat, lon = p.get("latitude"), p.get("longitude")
        if not (lat and lon):
            continue
        key = f"{lat},{lon}"
        if key not in cache or cache[key] is None:
            t = tract_of(lat, lon)
            if t is not None:  # don't cache failures; retry next run
                cache[key] = t
                CACHE.write_text(json.dumps(cache))
        t = cache.get(key)
        if not t:
            continue
        geoid = "".join(t)
        if geoid not in tract_data:
            tract_data[geoid] = acs(*t)
        p.update(tract_data[geoid])
    SAMPLE.write_text(json.dumps(props, indent=1))
    print(f"distinct tracts: {len(tract_data)}")
    for g, d in tract_data.items():
        print(f"  tract {g}: income={d['tract_median_income']} poverty={d['tract_poverty_pct']}% "
              f"ownership={d['tract_homeownership_pct']}% vacancy={d['tract_vacancy_pct']}%")


if __name__ == "__main__":
    main()
