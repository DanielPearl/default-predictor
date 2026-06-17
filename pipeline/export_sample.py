#!/usr/bin/env python3
"""
Export a sample of properties from the taxlot DB into properties_sample.json
for the website's "Properties" tab. Rows are properties; columns are the
features we can compute today from the taxlot base (the distress signals the
model will use). Run after ingest_taxlots.py.
"""
import json
import os
import random
import re
import sqlite3
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "taxlots.db"
OUT = ROOT / "properties_sample.json"
SAMPLE_SIZE = int(os.environ.get("SAMPLE_SIZE", "250"))
SAMPLE_SEED = int(os.environ.get("SAMPLE_SEED", "42"))
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
    # Deterministic, geographically diverse sample (random across the whole
    # county, fixed seed) so features vary instead of clustering in one block.
    where = """PRPCD_DESC = 'RESIDENTIAL IMPROVED'
          AND TOTALVAL1 > 0 AND TOTALVAL3 > 0
          AND OWNER1 <> '' AND SITEADDR <> ''
          AND SALEDATE NOT LIKE '%1900%' AND SALEPRICE > 0"""
    eligible = [r[0] for r in conn.execute(f"SELECT PROPERTYID FROM taxlots WHERE {where}")]
    random.seed(SAMPLE_SEED)
    chosen = random.sample(eligible, min(SAMPLE_SIZE, len(eligible)))
    rows = conn.execute(
        f"SELECT * FROM taxlots WHERE PROPERTYID IN ({','.join('?' * len(chosen))})", chosen).fetchall()

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
        sqft = int(r["BLDGSQFT"]) if r["BLDGSQFT"] else None
        ppsf = round(current / sqft) if sqft else None
        lot = int(r["A_T_SQFT"]) if r["A_T_SQFT"] else None
        val_per_lot = round(current / lot) if lot else None
        # Count owner names across OWNER1-3 (names within a field split on "&").
        names = []
        for f in ("OWNER1", "OWNER2", "OWNER3"):
            if r[f]:
                names += [n for n in r[f].split("&") if n.strip()]
        out.append({
            "property_id": r["PROPERTYID"] or "",
            "address": norm(r["SITEADDR"]),
            "owner": r["OWNER1"],
            "owner_count": len(names) or None,
            "owner_city": (r["OWNERCITY"] or "").title(),
            "owner_state": r["OWNERSTATE"] or "",
            "owner_zip": (r["OWNERZIP"] or "")[:5],
            "occupancy": "Owner-occupied" if owner_occ else "Absentee",
            "owner_type": "Entity" if ENTITY_RE.search(r["OWNER1"] or "") else "Individual",
            "year_built": r["YEARBUILT"] or "",
            "age": age,
            "sqft": sqft,
            "units": int(r["UNITS"]) if r["UNITS"] else None,
            "lot_sqft": lot,
            "land_use": r["LANDUSE"] or "",
            "site_zip": (r["SITEZIP"] or "")[:5],
            "land_value": int(land) if land else None,
            "building_value": int(bldg) if bldg else None,
            "land_share_pct": land_share,
            "assessed_value": int(current),
            "assessed_value_prior": int(prior),
            "assessed_value_mid": int(r["TOTALVAL2"]) if r["TOTALVAL2"] else None,
            "price_per_sqft": ppsf,
            "value_per_lot_sqft": val_per_lot,
            "value_trend_pct": trend,
            "tax_code": r["TAXCODE"] or "",
            "last_sale_date": r["SALEDATE"],
            "tenure_years": tenure_years(r["SALEDATE"]),
            "last_sale_price": int(sale) if sale else None,
            "appreciation": appreciation,
        })

    OUT.write_text(json.dumps(out, indent=1))
    print(f"Wrote {len(out)} properties to {OUT}")


if __name__ == "__main__":
    main()
