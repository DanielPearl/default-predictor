#!/usr/bin/env python3
"""
Export a sample of properties from the taxlot DB into properties_sample.json
for the website's "Properties" tab. Rows are properties; columns are the
features we can compute today from the taxlot base (the distress signals the
model will use). Run after ingest_taxlots.py.
"""
import json
import re
import sqlite3
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "taxlots.db"
OUT = ROOT / "properties_sample.json"
SAMPLE_SIZE = 60
TODAY = date(2026, 6, 16)

ENTITY_RE = re.compile(
    r"\b(LLC|INC|CORP|TRUST|LP|LLP|LTD|COMPANY|PARTNERS|PROPERTIES|HOLDINGS|"
    r"INVESTMENTS|CAPITAL|BANK|ASSOCIATION|CHURCH|HOMES|GROUP)\b"
    r"|CITY OF|STATE OF|COUNTY OF", re.I)


def norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().upper())


def tenure_years(saledate):
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", saledate or "")
    if not m:
        return None
    mm, dd, yyyy = (int(x) for x in m.groups())
    try:
        d = date(yyyy, mm, dd)
    except ValueError:
        return None
    return round((TODAY - d).days / 365.25, 1)


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    # Note on value years: TOTALVAL1 is the 2023 roll, TOTALVAL3 is the current
    # (2025) roll, so VAL3 is the latest and the trend is VAL3 vs VAL1.
    rows = conn.execute("""
        SELECT * FROM taxlots
        WHERE PRPCD_DESC = 'RESIDENTIAL IMPROVED'
          AND TOTALVAL1 > 0 AND TOTALVAL3 > 0
          AND OWNER1 <> '' AND SITEADDR <> ''
          AND SALEDATE NOT LIKE '%1900%' AND SALEPRICE > 0
        ORDER BY parcel_key
        LIMIT ?
    """, (SAMPLE_SIZE,)).fetchall()

    out = []
    for r in rows:
        prior, current = r["TOTALVAL1"], r["TOTALVAL3"]
        trend = round((current - prior) / prior * 100, 1) if prior else None
        owner_occ = norm(r["OWNERADDR"]) == norm(r["SITEADDR"])
        try:
            age = TODAY.year - int(r["YEARBUILT"]) if r["YEARBUILT"] else None
        except ValueError:
            age = None
        land, bldg = r["LANDVAL1"], r["BLDGVAL1"]
        land_share = round(land / (land + bldg) * 100) if land and bldg else None
        sale = r["SALEPRICE"]
        appreciation = round(current / sale, 2) if sale else None
        out.append({
            "property_id": r["PROPERTYID"] or "",
            "address": norm(r["SITEADDR"]),
            "owner": r["OWNER1"],
            "owner_city": (r["OWNERCITY"] or "").title(),
            "owner_state": r["OWNERSTATE"] or "",
            "occupancy": "Owner-occupied" if owner_occ else "Absentee",
            "owner_type": "Entity" if ENTITY_RE.search(r["OWNER1"] or "") else "Individual",
            "year_built": r["YEARBUILT"] or "",
            "age": age,
            "sqft": int(r["BLDGSQFT"]) if r["BLDGSQFT"] else None,
            "units": int(r["UNITS"]) if r["UNITS"] else None,
            "lot_sqft": int(r["A_T_SQFT"]) if r["A_T_SQFT"] else None,
            "land_value": int(land) if land else None,
            "land_share_pct": land_share,
            "assessed_value": int(current),
            "assessed_value_prior": int(prior),
            "value_trend_pct": trend,
            "last_sale_date": r["SALEDATE"],
            "tenure_years": tenure_years(r["SALEDATE"]),
            "last_sale_price": int(sale) if sale else None,
            "appreciation": appreciation,
        })

    OUT.write_text(json.dumps(out, indent=1))
    print(f"Wrote {len(out)} properties to {OUT}")


if __name__ == "__main__":
    main()
