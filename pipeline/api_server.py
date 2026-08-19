#!/usr/bin/env python3
"""
Tiny read-only API that serves the FULL taxlot base (all Multnomah parcels,
~242k) as pages of 20 for the website's Properties tab, straight from the
droplet database. Rows carry the same keys as the enriched table; parcels we
have enriched (the weekly samples) get those extra columns merged in.

Runs on 127.0.0.1:8001 behind nginx (location /api/). Stdlib only.
"""
import json
import math
import os
import re
import sqlite3
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "taxlots.db"
PAGE_SIZE = 20

ENTITY_RE = re.compile(
    r"\b(LLC|INC|CORP|TRUST|LP|LLP|LTD|COMPANY|PARTNERS|PROPERTIES|HOLDINGS|"
    r"INVESTMENTS|CAPITAL|BANK|ASSOCIATION|CHURCH|HOMES|GROUP)\b"
    r"|CITY OF|STATE OF|COUNTY OF", re.I)


def norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().upper())


def tenure(saledate):
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", saledate or "")
    if not m:
        return None
    mm, dd, yyyy = (int(x) for x in m.groups())
    try:
        d = date(yyyy, mm, dd)
    except ValueError:
        return None
    return round((date.today() - d).days / 365.25, 1)


def base_record(r, asof):
    """Map a raw taxlot row to the friendly keys the frontend uses (same
    derivations as export_sample.py, guarded for blank/zero fields)."""
    def num(v):
        try:
            f = float(v)
            return f if f else None
        except (TypeError, ValueError):
            return None

    current, prior, mid = num(r["TOTALVAL3"]), num(r["TOTALVAL1"]), num(r["TOTALVAL2"])
    land, bldg, sale = num(r["LANDVAL1"]), num(r["BLDGVAL1"]), num(r["SALEPRICE"])
    sqft, lot = num(r["BLDGSQFT"]), num(r["A_T_SQFT"])
    saledate = "" if "1900" in (r["SALEDATE"] or "") else (r["SALEDATE"] or "")
    names = []
    for f in ("OWNER1", "OWNER2", "OWNER3"):
        if r[f]:
            names += [n for n in r[f].split("&") if n.strip()]
    try:
        age = date.today().year - int(r["YEARBUILT"]) if r["YEARBUILT"] else None
    except ValueError:
        age = None
    return {
        "scraped_date": asof,
        "property_id": r["PROPERTYID"] or "",
        "address": norm(r["SITEADDR"]),
        "owner": r["OWNER1"] or "",
        "owner_count": len(names) or None,
        "owner_city": (r["OWNERCITY"] or "").title(),
        "owner_state": r["OWNERSTATE"] or "",
        "owner_zip": (r["OWNERZIP"] or "")[:5],
        "occupancy": "Owner-occupied" if norm(r["OWNERADDR"]) == norm(r["SITEADDR"]) else "Absentee",
        "owner_type": "Entity" if ENTITY_RE.search(r["OWNER1"] or "") else "Individual",
        "year_built": r["YEARBUILT"] or "",
        "age": age,
        "sqft": int(sqft) if sqft else None,
        "units": int(r["UNITS"]) if r["UNITS"] else None,
        "lot_sqft": int(lot) if lot else None,
        "land_use": r["LANDUSE"] or "",
        "site_zip": (r["SITEZIP"] or "")[:5],
        "land_value": int(land) if land else None,
        "building_value": int(bldg) if bldg else None,
        "land_share_pct": round(land / (land + bldg) * 100) if land and bldg else None,
        "assessed_value": int(current) if current else None,
        "assessed_value_prior": int(prior) if prior else None,
        "assessed_value_mid": int(mid) if mid else None,
        "price_per_sqft": round(current / sqft) if current and sqft else None,
        "value_per_lot_sqft": round(current / lot) if current and lot else None,
        "value_trend_pct": round((current - prior) / prior * 100, 1) if current and prior else None,
        "tax_code": r["TAXCODE"] or "",
        "last_sale_date": saledate,
        "tenure_years": tenure(saledate),
        "last_sale_price": int(sale) if sale else None,
        "appreciation": round(current / sale, 2) if current and sale else None,
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        u = urlparse(self.path)
        if u.path.rstrip("/") != "/api/properties":
            self.send_error(404)
            return
        page = 1
        try:
            page = max(1, int(parse_qs(u.query).get("page", ["1"])[0]))
        except ValueError:
            pass
        conn = sqlite3.connect(DB)
        conn.row_factory = sqlite3.Row
        total = conn.execute("SELECT COUNT(*) FROM taxlots").fetchone()[0]
        pages = max(1, math.ceil(total / PAGE_SIZE))
        page = min(page, pages)
        asof = date.fromtimestamp(os.path.getmtime(DB)).isoformat()
        rows = conn.execute("SELECT * FROM taxlots ORDER BY parcel_key LIMIT ? OFFSET ?",
                            (PAGE_SIZE, (page - 1) * PAGE_SIZE)).fetchall()
        recs = [base_record(r, asof) for r in rows]
        # Merge enriched columns where we have them (latest scrape wins).
        ids = [x["property_id"] for x in recs if x["property_id"]]
        if ids:
            try:
                enriched = {}
                for er in conn.execute(
                        "SELECT * FROM properties WHERE property_id IN (%s) "
                        "ORDER BY scraped_date" % ",".join("?" * len(ids)), ids):
                    enriched[er["property_id"]] = dict(er)
                for x in recs:
                    e = enriched.get(x["property_id"])
                    if e:
                        x.update({k: v for k, v in e.items() if v not in (None, "")})
            except sqlite3.OperationalError:
                pass  # no properties table yet
        conn.close()
        body = json.dumps({"total": total, "page": page, "pages": pages,
                           "size": PAGE_SIZE, "results": recs}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep the service log quiet
        pass


if __name__ == "__main__":
    print("api_server on 127.0.0.1:8001")
    HTTPServer(("127.0.0.1", 8001), Handler).serve_forever()
