#!/usr/bin/env python3
"""
Turn captured bankruptcy filings into a short, click-to-confirm candidate list.

Matches debtor names from the lake's bankruptcy captures against property
owners (taxlots OWNER1/OWNER2) -- all free, local, no PACER. Emits one row per
name-match with the PACER docket link and the parcel's site + mailing address,
so confirming it is a 10-second glance:

  open the PACER link -> read the debtor's address -> does it match the parcel?

Prioritized so you pay PACER as little as possible:
  * confidence=high   -> uncommon surname, near-certain; accept without paying
  * confidence=verify -> common surname; pull the PACER address to disambiguate

Identity, not residence: the debtor address need only match the owner's SITE or
MAILING address to confirm it's the same person (owner-occupied or absentee).

    python3 pipeline/bankruptcy_candidates.py
    python3 pipeline/bankruptcy_candidates.py --out data/bankruptcy_candidates.csv
Stdlib only.
"""
import csv
import glob
import gzip
import json
import re
import sys
from collections import Counter

import lake

LAKE = str(lake.LAKE_ROOT)
STOP = {"LLC", "INC", "TRUST", "TRUSTEE", "THE", "LIVING", "FAMILY", "ESTATE",
        "ET", "AL", "REVOCABLE", "CO", "LP", "LLP", "JR", "SR", "II", "III"}
COMMON_SURNAME = 60  # owner-parcels sharing a surname above this => "verify"


def toks(name):
    name = re.sub(r"[^A-Za-z ]", " ", (name or "").upper())
    return frozenset(t for t in name.split() if len(t) > 1 and t not in STOP)


def load_owners():
    """name-set -> list of parcel dicts; plus a surname frequency counter."""
    owners, surname_freq = {}, Counter()
    for f in glob.glob(f"{LAKE}/portlandmaps/taxlots/captured_date=*/*.ndjson.gz"):
        for line in gzip.open(f, "rt"):
            o = json.loads(line)
            parcel = {
                "rno": o.get("RNO"),
                "site": " ".join(x for x in (o.get("SITEADDR"), o.get("SITECITY"),
                                             o.get("SITEZIP")) if x).strip(),
                "mail": " ".join(x for x in (o.get("OWNERADDR"), o.get("OWNERCITY"),
                                             o.get("OWNERSTATE"), o.get("OWNERZIP")) if x).strip(),
            }
            for fld in ("OWNER1", "OWNER2"):
                raw = o.get(fld)
                ts = toks(raw)
                if len(ts) >= 2:
                    owners.setdefault(ts, []).append(parcel)
                    surname_freq[raw.split()[0].upper()] += 1  # owners are LAST-first
        break  # one (latest) partition is the current parcel base
    return owners, surname_freq


def load_cases():
    """Unique bankruptcy cases from every daily capture (dedup by case_number)."""
    cases = {}
    for f in sorted(glob.glob(f"{LAKE}/pacer-d-oregon/bankruptcy/captured_date=*/*.ndjson.gz")):
        for line in gzip.open(f, "rt"):
            r = json.loads(line)
            cn = r.get("case_number")
            if cn and cn not in cases:
                cases[cn] = r
    return cases


def main():
    out = "data/bankruptcy_candidates.csv"
    if "--out" in sys.argv:
        out = sys.argv[sys.argv.index("--out") + 1]

    owners, surname_freq = load_owners()
    cases = load_cases()
    print(f"owners: {len(owners):,} name-sets   bankruptcy cases: {len(cases):,}")

    rows = []
    for cn, r in cases.items():
        for part in re.split(r"\s+and\s+", r.get("debtor_name", ""), flags=re.I):
            ts = toks(part)
            if len(ts) < 2 or ts not in owners:
                continue
            parcels = owners[ts]
            surname = part.strip().split()[-1].upper() if part.strip() else ""
            freq = surname_freq.get(surname, 0)
            conf = "verify" if (freq > COMMON_SURNAME or len(parcels) > 3) else "high"
            rows.append({
                "confidence": conf,
                "case_number": cn,
                "chapter": r.get("chapter"),
                "office": r.get("office"),
                "debtor_name": part.strip(),
                "pacer_link": r.get("link"),
                "matched_owner_parcels": len(parcels),
                "rnos": ";".join(p["rno"] or "" for p in parcels[:5]),
                "site_address": parcels[0]["site"],
                "mailing_address": parcels[0]["mail"],
                "surname_freq": freq,
            })

    rows.sort(key=lambda x: (x["confidence"] != "high", x["surname_freq"]))
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else
                           ["confidence", "case_number", "debtor_name", "pacer_link"])
        w.writeheader()
        w.writerows(rows)

    hi = sum(1 for x in rows if x["confidence"] == "high")
    print(f"\ncandidates: {len(rows)}  ({hi} high-confidence/free, {len(rows) - hi} verify-via-PACER)")
    print(f"wrote {out}")
    for x in rows[:10]:
        print(f"  [{x['confidence']:6}] {x['case_number']:16} {x['debtor_name'][:28]:28} "
              f"-> {x['site_address'][:40]}")


if __name__ == "__main__":
    main()
