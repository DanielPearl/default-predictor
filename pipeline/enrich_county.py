#!/usr/bin/env python3
"""
Join Multnomah County open-data parcel fields onto properties_sample.json by
PROPID = our property_id. Adds the alternate account number (a foreign key into
the county's other systems) and the last deed type/date (how the current owner
acquired the property, which can flag a probate or foreclosure transfer).

Keyless ArcGIS open data, NO API key required. Run after enrich_sample.py.
"""
import json
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "properties_sample.json"
SVC = ("https://services5.arcgis.com/x7DNZL1YqNQVNykA/arcgis/rest/services"
       "/Multnomah_County_Taxlot_Parcels/FeatureServer/0/query")

# Decode the county's deed-type codes; distress-relevant ones are labeled.
DEED = {
    "WD": "Warranty", "SWD": "Special warranty", "BS": "Bargain & sale", "BSD": "Bargain & sale",
    "GD": "Grant", "CD": "Contract", "QCD": "Quitclaim", "DQT": "Quitclaim", "DEED": "Deed",
    "PRD": "Personal rep (probate)", "PR": "Personal rep (probate)", "HEIR": "Heir",
    "BKTRD": "Bank trustee (foreclosure)", "TRD": "Trustee (foreclosure)",
    "SD": "Sheriff (foreclosure)", "ESD": "Sheriff (foreclosure)", "JUD": "Judicial",
}


def deed_date(ms):
    if not ms:
        return ""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%m/%d/%Y")


def parse_exemption(s):
    # Field looks like " 18, SA, SA, ..."; the leading number is the exemption
    # code (if any); the repeated "SA" is per-year special-assessment noise.
    if not s:
        return ""
    first = s.split(",")[0].strip()
    return first if first.isdigit() else ""


def fetch(pids):
    by = {}
    for i in range(0, len(pids), 100):
        chunk = pids[i:i + 100]
        params = {
            "where": "PROPID IN (%s)" % ",".join("'%s'" % x for x in chunk),
            "outFields": "PROPID,ALTACCTNUM,DEED_TYPE,DEED_DATE,INST_NUM,IMP_COUNT,EXEMPTION",
            "returnGeometry": "false", "f": "json",
        }
        req = urllib.request.Request(SVC, data=urllib.parse.urlencode(params).encode())
        r = json.load(urllib.request.urlopen(req, timeout=40))
        for f in r.get("features", []):
            by[f["attributes"]["PROPID"]] = f["attributes"]
    return by


def main():
    props = json.loads(SAMPLE.read_text())
    by = fetch([p["property_id"] for p in props if p.get("property_id")])
    matched = 0
    for p in props:
        a = by.get(p["property_id"])
        if a:
            matched += 1
            dt = a.get("DEED_TYPE") or ""
            imp = (a.get("IMP_COUNT") or "").strip()
            p["alt_account"] = a.get("ALTACCTNUM") or ""
            p["deed_type"] = DEED.get(dt, dt)
            p["deed_date"] = deed_date(a.get("DEED_DATE"))
            p["instrument_num"] = a.get("INST_NUM") or ""
            p["improvements"] = int(imp) if imp.isdigit() else None
            p["exemption"] = parse_exemption(a.get("EXEMPTION"))
        else:
            for k in ("alt_account", "deed_type", "deed_date", "instrument_num", "exemption"):
                p.setdefault(k, "")
            p.setdefault("improvements", None)
    SAMPLE.write_text(json.dumps(props, indent=1))
    print(f"matched {matched}/{len(props)} on PROPID")
    print("deed types:", dict(Counter(p["deed_type"] for p in props)))


if __name__ == "__main__":
    main()
