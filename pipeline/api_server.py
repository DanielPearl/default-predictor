#!/usr/bin/env python3
"""
Tiny read-only API behind nginx (location /api/). Stdlib only. Routes:

  /api/properties?page=N  full taxlot base (all Multnomah parcels, ~242k) as
                          pages of 20 for the Properties tab, with enriched
                          columns merged in where we have them.
  /api/uploads            the data-lake catalog (one row per raw file landed)
                          for the Uploads tab.

Runs on 127.0.0.1:8001.
"""
import gzip
import json
import math
import os
import re
import sqlite3
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import catalog  # lake-catalog reader (sibling module)
import lake      # lake storage (for file previews)

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "taxlots.db"
PAGE_SIZE = 20

ENTITY_RE = re.compile(
    r"\b(LLC|INC|CORP|TRUST|LP|LLP|LTD|COMPANY|PARTNERS|PROPERTIES|HOLDINGS|"
    r"INVESTMENTS|CAPITAL|BANK|ASSOCIATION|CHURCH|HOMES|GROUP)\b"
    r"|CITY OF|STATE OF|COUNTY OF", re.I)

# Keywords for the Owner-type filter (approximate SQL LIKE match on OWNER1).
ENTITY_KEYWORDS = ["LLC", "INC", "CORP", "TRUST", "LTD", "COMPANY", "PARTNERS",
                   "PROPERTIES", "HOLDINGS", "INVESTMENTS", "CAPITAL", "BANK",
                   "ASSOCIATION", "CHURCH", "HOMES", "GROUP",
                   "CITY OF", "STATE OF", "COUNTY OF"]


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
    def _send_json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        path = u.path.rstrip("/")
        if path == "/api/properties":
            return self._properties(u)
        if path == "/api/uploads/preview":
            return self._upload_preview(u)
        if path == "/api/uploads":
            return self._uploads(u)
        self.send_error(404)

    def _uploads(self, u):
        try:
            rows = catalog.list_uploads()
        except Exception:  # noqa: BLE001  (no catalog yet)
            rows = []
        self._send_json(rows)

    def _file_total(self, rel):
        """Exact row count for a landed file, straight from the catalog."""
        try:
            for r in catalog.list_uploads():
                if r.get("relpath") == rel:
                    return r.get("rows")
        except Exception:  # noqa: BLE001
            pass
        return None

    def _upload_preview(self, u):
        """A paged, searchable window into one landed lake file so the site can
        browse the table inside it. Reads only files under the lake root."""
        qs = parse_qs(u.query)
        rel = (qs.get("relpath") or [""])[0]
        try:
            limit = max(1, min(200, int((qs.get("limit") or ["25"])[0])))
        except ValueError:
            limit = 25
        try:
            page = max(1, int((qs.get("page") or ["1"])[0]))
        except ValueError:
            page = 1
        q = (qs.get("q") or [""])[0].strip().lower()
        base = lake.LAKE_ROOT.resolve()
        target = (base / rel).resolve()
        if base not in target.parents or not target.is_file() or not rel.endswith(".ndjson.gz"):
            self.send_error(404)
            return

        start = (page - 1) * limit
        rows, cols, seen = [], [], set()

        def addcols(obj):
            for k in obj:
                if k not in seen:
                    seen.add(k)
                    cols.append(k)

        try:
            with gzip.open(target, "rt", encoding="utf-8") as f:
                if q:
                    # scan + filter: substring match across all values
                    total = 0
                    for line in f:
                        try:
                            obj = json.loads(line)
                        except ValueError:
                            continue
                        hay = " ".join(str(v) for v in obj.values()
                                       if v not in (None, "")).lower()
                        if q not in hay:
                            continue
                        if start <= total < start + limit:
                            addcols(obj)
                            rows.append(obj)
                        total += 1
                else:
                    # no filter: total is known from the catalog, read page window
                    total = self._file_total(rel)
                    i = 0
                    for line in f:
                        if i >= start:
                            try:
                                obj = json.loads(line)
                            except ValueError:
                                i += 1
                                continue
                            addcols(obj)
                            rows.append(obj)
                            if len(rows) >= limit:
                                break
                        i += 1
                    if total is None:
                        total = i
        except OSError:
            self.send_error(404)
            return

        if not cols:  # empty page: still return the column list
            try:
                with gzip.open(target, "rt", encoding="utf-8") as f:
                    addcols(json.loads(f.readline()))
            except Exception:  # noqa: BLE001
                pass

        pages = max(1, math.ceil((total or 0) / limit))
        self._send_json({"relpath": rel, "columns": cols, "rows": rows,
                         "page": page, "pages": pages, "total": total or 0,
                         "limit": limit, "q": q, "start": start})

    def _properties(self, u):
        qs = parse_qs(u.query)
        try:
            page = max(1, int(qs.get("page", ["1"])[0]))
        except ValueError:
            page = 1
        q = (qs.get("q") or [""])[0].strip()
        occ = (qs.get("occ") or [""])[0]
        otype = (qs.get("otype") or [""])[0]
        ostate = (qs.get("ostate") or [""])[0]

        where, params = [], []
        if q:
            like = f"%{q}%"
            where.append("(OWNER1 LIKE ? OR SITEADDR LIKE ? OR PROPERTYID LIKE ? "
                         "OR OWNERCITY LIKE ?)")
            params += [like, like, like, like]
        if occ == "owner":
            where.append("TRIM(UPPER(OWNERADDR)) = TRIM(UPPER(SITEADDR)) "
                         "AND TRIM(OWNERADDR) <> ''")
        elif occ == "absentee":
            where.append("TRIM(UPPER(OWNERADDR)) <> TRIM(UPPER(SITEADDR))")
        if otype in ("entity", "individual"):
            ent = "(" + " OR ".join(["OWNER1 LIKE ?"] * len(ENTITY_KEYWORDS)) + ")"
            where.append(ent if otype == "entity" else "NOT " + ent)
            params += [f"%{k}%" for k in ENTITY_KEYWORDS]
        if ostate == "or":
            where.append("UPPER(TRIM(OWNERSTATE)) = 'OR'")
        elif ostate == "oos":
            where.append("UPPER(TRIM(OWNERSTATE)) <> 'OR' AND TRIM(OWNERSTATE) <> ''")
        wsql = (" WHERE " + " AND ".join(where)) if where else ""

        conn = sqlite3.connect(DB)
        conn.row_factory = sqlite3.Row
        grand = conn.execute("SELECT COUNT(*) FROM taxlots").fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM taxlots" + wsql, params).fetchone()[0]
        pages = max(1, math.ceil(total / PAGE_SIZE))
        page = min(page, pages)
        asof = date.fromtimestamp(os.path.getmtime(DB)).isoformat()
        rows = conn.execute(
            "SELECT * FROM taxlots" + wsql + " ORDER BY parcel_key LIMIT ? OFFSET ?",
            params + [PAGE_SIZE, (page - 1) * PAGE_SIZE]).fetchall()
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
        body = json.dumps({"total": total, "grand_total": grand, "page": page,
                           "pages": pages, "size": PAGE_SIZE, "results": recs}).encode()
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
