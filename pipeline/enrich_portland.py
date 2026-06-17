#!/usr/bin/env python3
"""
Join three keyless City of Portland open-data layers onto properties_sample.json:
  - Rental Portfolio (regulated/affordable rental projects) by R_Number = property_id
  - Residential Demolition Permits by taxlot STATE_ID
  - Historic/Conservation District status by taxlot STATE_ID

No API key required. Run after enrich_census.py.
"""
import json
import sqlite3
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "properties_sample.json"
DB = ROOT / "data" / "taxlots.db"
BASE = "https://www.portlandmaps.com/od/rest/services/"
RENTAL = BASE + "COP_OpenData_PlanningDevelopment/MapServer/221/query"
DEMO = BASE + "COP_OpenData_PlanningDevelopment/MapServer/126/query"
HIST = BASE + "COP_OpenData_ZoningCode/MapServer/123/query"


def norm_sid(s):
    """Normalize a taxlot state id for joining across sources with different
    spacing/zero-padding: '1N1E02AC  200' / '1N1E02AC  -00200' -> '1N1E02AC200'."""
    if not s:
        return ""
    parts = s.replace("-", " ").split()
    if len(parts) >= 2:
        num = "".join(c for c in parts[-1] if c.isdigit())
        return parts[0].upper() + (str(int(num)) if num else "")
    return s.replace(" ", "").upper()


def pull(url, fields):
    """Pull all records (paginated via exceededTransferLimit)."""
    out, offset = [], 0
    while True:
        q = urllib.parse.urlencode({"where": "1=1", "outFields": fields, "returnGeometry": "false",
                                    "resultOffset": offset, "resultRecordCount": 1000, "f": "json"})
        resp = json.load(urllib.request.urlopen(url + "?" + q, timeout=40))
        feats = resp.get("features", [])
        out += [f["attributes"] for f in feats]
        if not feats or not resp.get("exceededTransferLimit"):
            return out
        offset += len(feats)


def main():
    props = json.loads(SAMPLE.read_text())
    pids = [p["property_id"] for p in props]
    conn = sqlite3.connect(DB)
    sid = {r[0]: r[1] for r in conn.execute(
        "SELECT PROPERTYID, STATE_ID FROM taxlots WHERE PROPERTYID IN (%s)" % ",".join("?" * len(pids)), pids)}

    rentals = {r.get("R_Number") for r in pull(RENTAL, "R_Number")}
    demos = {}
    for r in pull(DEMO, "STATEIDKEY,YEAR"):
        demos.setdefault(norm_sid(r.get("STATEIDKEY")), r.get("YEAR"))
    hist = {}
    for r in pull(HIST, "STATE_ID,DistName,NRStatus"):
        hist.setdefault(norm_sid(r.get("STATE_ID")), r.get("DistName") or r.get("NRStatus") or "Historic")

    n_r = n_d = n_h = 0
    for p in props:
        ns = norm_sid(sid.get(p["property_id"], ""))
        p["rental_regulated"] = "Yes" if p["property_id"] in rentals else "No"
        p["demolition"] = "Yes" if ns in demos else "No"
        p["historic_district"] = hist.get(ns, "")
        n_r += p["rental_regulated"] == "Yes"
        n_d += p["demolition"] == "Yes"
        n_h += bool(p["historic_district"])
    SAMPLE.write_text(json.dumps(props, indent=1))
    print(f"layer sizes: rentals={len(rentals)} demos={len(demos)} historic={len(hist)}")
    print(f"matches in sample: rental_regulated={n_r} demolition={n_d} historic={n_h}")


if __name__ == "__main__":
    main()
