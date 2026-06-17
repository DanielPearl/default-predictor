#!/usr/bin/env python3
"""
Flag POSSIBLE owner bankruptcies by matching owner names against the Oregon
Bankruptcy Court (court=orb) via CourtListener's free RECAP API. No PACER
account required.

Matching is by NAME, so a hit is a possible match to verify, not a certainty
(same-name people exist). Results are cached in data/bankruptcy_cache.json.
Run after enrich_county.py.
"""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "properties_sample.json"
CACHE = ROOT / "data" / "bankruptcy_cache.json"
API = "https://www.courtlistener.com/api/rest/v4/search/"
ENTITY = re.compile(r"\b(LLC|INC|CORP|TRUST|LP|COMPANY|BANK|PROPERTIES|HOLDINGS|CHURCH|CITY|COUNTY)\b", re.I)


def owner_names(owner):
    """'SCOTT,LINDA L' -> [('scott','linda','l')] (last, first, middle initial)."""
    out = []
    for part in owner.split("&"):
        part = part.strip()
        if ENTITY.search(part):
            continue
        if "," in part:
            last, rest = part.split(",", 1)
            toks = rest.strip().split()
        else:
            toks = part.split()
            last, toks = (toks[-1], toks[:-1]) if len(toks) >= 2 else ("", [])
        first = toks[0] if toks else ""
        mid = toks[1][0] if len(toks) >= 2 else ""
        last = re.sub(r"[^a-z]", "", last.lower())
        first = re.sub(r"[^a-z]", "", first.lower())
        mid = re.sub(r"[^a-z]", "", mid.lower())
        if last and first:
            out.append((last, first, mid))
    return out


def search(first, last):
    url = API + "?" + urllib.parse.urlencode({"type": "r", "court": "orb", "q": f"{first} {last}"})
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    for _ in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r).get("results") or []
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = int(e.headers.get("Retry-After", 30))
                print(f"  throttled; waiting {wait}s")
                time.sleep(wait)
                continue
            return []
        except Exception:
            time.sleep(3)
    return []


def best_match(results, first, last, mid):
    """Require party FIRST token == first and LAST token == last (correct name
    positions), and reject when both middle initials are present but differ."""
    for r in results:
        for party in (r.get("party") or []):
            toks = re.sub(r"[^a-z ]", "", party.lower()).split()
            if len(toks) < 2 or toks[0] != first or toks[-1] != last:
                continue
            party_mid = toks[1][0] if len(toks) >= 3 else ""
            if mid and party_mid and mid != party_mid:
                continue
            return {"chapter": r.get("chapter"), "date": r.get("dateFiled"),
                    "case": r.get("caseName"), "docket": r.get("docketNumber")}
    return None


def main():
    props = json.loads(SAMPLE.read_text())
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    hits = 0
    for i, p in enumerate(props, 1):
        owner = p.get("owner", "")
        if owner not in cache:
            found = None
            for last, first, mid in owner_names(owner):
                m = best_match(search(first, last), first, last, mid)
                if m:
                    found = m
                    break
                time.sleep(0.6)
            cache[owner] = found
            CACHE.write_text(json.dumps(cache, indent=1))
        m = cache[owner]
        p["bankruptcy_flag"] = "Yes" if m else "No"
        p["bankruptcy_chapter"] = ("Ch " + str(m["chapter"])) if m and m.get("chapter") else ""
        p["bankruptcy_date"] = m["date"] if m else ""
        if m:
            hits += 1
            print(f"  [{i}] possible match: {owner} -> {m['case']} (Ch {m['chapter']}, {m['date']})")
    SAMPLE.write_text(json.dumps(props, indent=1))
    print(f"\npossible bankruptcy matches: {hits}/{len(props)}")


if __name__ == "__main__":
    main()
