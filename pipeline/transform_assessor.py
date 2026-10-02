#!/usr/bin/env python3
"""
lake (raw PortlandMaps assessor)  ->  core_property  (cleaned)

The first lake -> core transform. It leaves the raw capture untouched and
writes a cleaned table where every property has an address: condo sub-units
(parking/garage) that PortlandMaps leaves address-less inherit their parent
parcel's street address, with the unit appended from the legal description.

    python3 pipeline/transform_assessor.py

Runs after collect_portlandmaps.py. Idempotent: rebuilds core_property from
the latest capture each run. Stdlib only.
"""
import gzip
import json
import re
import sys

import catalog
import lake

SOURCE, DATASET = "PortlandMaps", "assessor"
WS = re.compile(r"\s+")
UNIT_RE = re.compile(r"\b(?:UNIT|LOT)\s+([A-Z0-9][A-Z0-9.\-/]*)", re.I)
# PortlandMaps puts a tax levy code in the address field for some accounts
# (common areas, right-of-way). It is not a street address -- don't treat it
# as one, and never let a sub-unit inherit it.
PLACEHOLDER_RE = re.compile(r"^LEVY\s+CODE\b", re.I)

COLS = ["property_id", "state_id", "parent_state_id", "account_status", "owner",
        "address", "address_source", "unit", "raw_address", "city", "state",
        "zip_code", "neighborhood", "legal_description", "market_value",
        "sale_date", "sale_price", "year_built", "square_feet", "latitude",
        "longitude", "captured_date", "source"]


def norm(s):
    return WS.sub(" ", (s or "").strip())


def real_addr(s):
    """A usable street address, or None for blanks and levy-code placeholders."""
    a = norm(s)
    return a if (a and not PLACEHOLDER_RE.match(a)) else None


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_unit(legal):
    legal = legal or ""
    up = legal.upper()
    m = UNIT_RE.search(legal)
    tok = m.group(1) if m else None
    kind = "parking" if "PARKING" in up else "garage" if "GARAGE" in up else None
    if tok and kind:
        return f"Unit {tok} ({kind})"
    if tok:
        return f"Unit {tok}"
    if kind:
        return f"{kind.capitalize()} unit"
    return None


def latest_capture():
    best = None
    for r in catalog.list_uploads():
        if r["source"] == SOURCE and r["dataset"] == DATASET:
            if best is None or (r["status"] == "complete" and best["status"] != "complete"):
                best = r
    return best


def main():
    cap = latest_capture()
    if not cap:
        sys.exit("no assessor capture in the lake yet")
    path = lake.LAKE_ROOT / cap["relpath"]
    if not path.exists():
        sys.exit(f"missing lake file: {path}")
    captured_date = cap["captured_date"]
    print(f"transform {cap['relpath']} ({cap.get('rows')} rows) -> core_property", flush=True)

    # pass 1 -- index every direct (non-null) address by its state_id, so a
    # sub-unit can look up its parent parcel's address.
    addr_by_sid = {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            sid, a = norm(r.get("state_id")), real_addr(r.get("address"))
            if sid and a:
                addr_by_sid[sid] = a

    # pass 2 -- resolve each record's address and write the cleaned row.
    conn = catalog.connect()
    catalog.migrate(conn)
    conn.execute("DELETE FROM core_property")
    ins = (f"INSERT OR REPLACE INTO core_property ({','.join(COLS)}) "
           f"VALUES ({','.join('?' * len(COLS))})")
    stats = {"direct": 0, "inherited": 0, "placeholder": 0, "none": 0}
    batch = []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            raw = norm(r.get("address"))
            raw_real = real_addr(raw)
            unit = parse_unit(r.get("legal_description"))
            parent = norm(r.get("parent_state_id"))
            if raw_real:
                address, src = raw_real, "direct"
            elif parent in addr_by_sid:
                address = norm(addr_by_sid[parent] + ((" " + unit) if unit else ""))
                src = "inherited"
            elif raw:
                address, src = None, "placeholder"   # had a levy code, not a street
            else:
                address, src = None, "none"
            stats[src] += 1
            batch.append((
                r.get("property_id"), norm(r.get("state_id")), parent or None,
                r.get("account_status_code"), norm(r.get("owner")) or None,
                address, src, unit, raw or None,
                r.get("city"), r.get("state"), r.get("zip_code"),
                r.get("neighborhood"), norm(r.get("legal_description")) or None,
                num(r.get("market_value")), r.get("sale_date"), num(r.get("sale_price")),
                norm(r.get("year_built")) or None, num(r.get("square_feet")),
                num(r.get("latitude")), num(r.get("longitude")),
                captured_date, SOURCE))
            if len(batch) >= 5000:
                conn.executemany(ins, batch)
                batch = []
    if batch:
        conn.executemany(ins, batch)
    conn.commit()
    conn.close()
    tot = sum(stats.values())
    print(f"wrote {tot:,} rows -> core_property  "
          f"(direct={stats['direct']:,}  inherited={stats['inherited']:,}  "
          f"placeholder={stats['placeholder']:,}  none={stats['none']:,})", flush=True)


if __name__ == "__main__":
    main()
