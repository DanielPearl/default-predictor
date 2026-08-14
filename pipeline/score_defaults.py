#!/usr/bin/env python3
"""
v0 rule-based default-risk score (heuristic, until DART labels let us train a
real model). Reads the served properties JSON (latest scrape only), applies
transparent weighted signals, and writes defaults.json: the flagged properties
in score order, each carrying the list of reasons (signal, points) that put it
on the list. Those reasons power the "?" popup on the Defaults tab.

Usage: score_defaults.py [properties.json] [defaults.json]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "properties_sample.json"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "defaults.json"
THRESHOLD = 25


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def score(p):
    """Return (points, reasons). Weights follow the signal tiers: distress
    events > financial stress proxies > ownership risk > area context."""
    r = []

    # Tier 1: direct distress events
    if p.get("probate_flag") == "Yes":
        r.append(("Acquired through probate; owner likely deceased", 30))
    if p.get("bankruptcy_recent") == "Yes":
        r.append(("Owner has a recent (possible) bankruptcy filing", 25))
    elif p.get("bankruptcy_flag") == "Yes":
        r.append(("Owner has an older (possible) bankruptcy filing", 10))
    if num(p.get("violation_vacant")):
        r.append(("Vacant or derelict-building code case", 30))
    for key, label in (("violation_trash", "Trash or debris code case"),
                       ("violation_overgrowth", "Overgrown-yard code case")):
        if num(p.get(key)):
            r.append((label, 8))

    # Tier 2: financial-stress proxies
    trend = num(p.get("value_trend_pct"))
    if trend is not None and trend < -5:
        r.append((f"Assessed value falling ({trend:+.1f}%)", 15))
    elif trend is not None and trend < 0:
        r.append((f"Assessed value slipping ({trend:+.1f}%)", 8))
    apprec, tenure = num(p.get("appreciation")), num(p.get("tenure_years"))
    if apprec is not None and apprec < 0.9:
        r.append((f"Worth less than purchase price ({apprec}x); likely thin equity", 20))
    elif apprec is not None and tenure is not None and apprec < 1.05 and tenure < 5:
        r.append(("Recent purchase with little appreciation; thin equity", 15))
    ysp = num(p.get("years_since_permit"))
    if ysp is not None and ysp >= 20:
        r.append((f"No building permits in {int(ysp)} years (deferred maintenance)", 5))

    # Tier 3: ownership risk
    if p.get("occupancy") == "Absentee":
        r.append(("Absentee owner", 8))
        if p.get("owner_state") and p.get("owner_state") != "OR":
            r.append(("Owner lives out of state", 5))
    oc = num(p.get("owner_count"))
    if oc is not None and oc >= 3:
        r.append(("Three or more owners on title (heirs or joint ownership)", 8))
    if p.get("owner_type") == "Entity":
        r.append(("Owned by a company or trust", 3))

    # Tier 4: area context
    tv = num(p.get("tract_vacancy_pct"))
    if tv is not None and tv >= 12:
        r.append((f"High neighborhood vacancy ({tv}%)", 4))

    return sum(pts for _, pts in r), r


def main():
    props = json.loads(SRC.read_text())
    latest = max((p.get("scraped_date") or "" for p in props), default="")
    props = [p for p in props if (p.get("scraped_date") or "") == latest] or props

    flagged = []
    for p in props:
        pts, reasons = score(p)
        if pts >= THRESHOLD:
            q = dict(p)
            q["default_score"] = pts
            q["default_reasons"] = [{"reason": t, "points": n} for t, n in reasons]
            flagged.append(q)
    flagged.sort(key=lambda x: -x["default_score"])
    OUT.write_text(json.dumps(flagged, indent=1))
    print(f"scored {len(props)} properties (scrape {latest}); "
          f"{len(flagged)} flagged at threshold {THRESHOLD} -> {OUT}")
    for q in flagged[:5]:
        print(f"  {q['default_score']:>3}  {q.get('address')}  "
              f"[{'; '.join(x['reason'] for x in q['default_reasons'][:3])}]")


if __name__ == "__main__":
    main()
