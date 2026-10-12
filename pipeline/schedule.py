#!/usr/bin/env python3
"""
Seed schedule.json -- the editable scheduler config AND what the site shows.

This is the single source of truth for scheduling: one flat list of jobs, each
with its display info, its data source, the command it runs, and its timing
(cadence + time of day + day). The site reads it to render the scheduler table;
edits from the UI (via the API) rewrite it; apply_schedule.py turns it into the
droplet crontab. Times are LOCAL (Pacific) -- the droplet's timezone is set to
America/Los_Angeles so cron fires at the times shown.

Running this RESEEDS the file from the definitions below (first-time setup, or
to reset). After that, prefer editing via the UI so your changes aren't lost.

    python3 pipeline/schedule.py [out.json]      # default: schedule.json
"""
import json
import os
import sys

import collect_arcgis as ca

EXPORT = "EXPORT_UPLOADS=/var/www/default-predictor/uploads.json"
AB = {k: v["about"] for k, v in ca.DATASETS.items()}

JOBS = [
    {"id": "bankruptcy", "name": "Bankruptcy Filings", "dataset": "bankruptcy",
     "source": "PACER (D. Oregon)", "color": "#58a6ff",
     "source_url": "https://ecf.orb.uscourts.gov/cgi-bin/rss_outside.pl",
     "cmd": f"{EXPORT} ONCE=1 python3 pipeline/collect_bankruptcy.py && "
            "python3 pipeline/bankruptcy_candidates.py --out data/bankruptcy_candidates.csv && "
            "python3 pipeline/bankruptcy_track.py export data/owner_bankruptcy.json",
     "cadence": "daily", "hour": 4, "minute": 0, "dow": None, "dom": None,
     "enabled": True, "continuous": False,
     "what": "New bankruptcy filings — debtor, case, chapter, division (RSS feed)",
     "why": "Owner bankruptcy is a pre-foreclosure life event",
     "note": "The RSS feed is a rolling ~24h window, so daily keeps it complete"},

    {"id": "permits", "name": "Building Permits", "dataset": "permits",
     "source": "PortlandMaps", "color": "#2dd4bf",
     "source_url": ca.DATASETS["permits"]["url"],
     "cmd": f"{EXPORT} python3 pipeline/collect_arcgis.py permits",
     "cadence": "weekly", "hour": 3, "minute": 0, "dow": 0, "dom": None,
     "enabled": True, "continuous": False,
     "what": AB["permits"], "why": "Permit activity (or its absence) signals investment vs neglect",
     "note": ""},

    {"id": "demolitions", "name": "Demolition Permits", "dataset": "demolitions",
     "source": "PortlandMaps", "color": "#2dd4bf",
     "source_url": ca.DATASETS["demolitions"]["url"],
     "cmd": f"{EXPORT} python3 pipeline/collect_arcgis.py demolitions",
     "cadence": "weekly", "hour": 3, "minute": 0, "dow": 0, "dom": None,
     "enabled": True, "continuous": False,
     "what": AB["demolitions"], "why": "Demolition filings flag distress and redevelopment",
     "note": ""},

    {"id": "assessor", "name": "Assessor Roll", "dataset": "assessor",
     "source": "PortlandMaps", "color": "#a78bfa",
     "source_url": "https://www.portlandmaps.com/api/assessor/",
     "cmd": f"{EXPORT} python3 pipeline/collect_portlandmaps.py",
     "cadence": "monthly", "hour": 2, "minute": 0, "dow": None, "dom": 1,
     "enabled": True, "continuous": False,
     "what": "County assessor roll — owner, value, sale, legal, location",
     "why": "Core property, ownership, and the 3-year value trend", "note": ""},

    {"id": "taxlots", "name": "Taxlots", "dataset": "taxlots",
     "source": "PortlandMaps", "color": "#a78bfa",
     "source_url": ca.DATASETS["taxlots"]["url"],
     "cmd": f"{EXPORT} python3 pipeline/collect_arcgis.py taxlots && "
            "python3 pipeline/ingest_taxlots.py",
     "cadence": "monthly", "hour": 2, "minute": 30, "dow": None, "dom": 1,
     "enabled": True, "continuous": False,
     "what": AB["taxlots"], "why": "Parcel base; owner mailing vs site address (absentee)",
     "note": ""},

    {"id": "rental_portfolio", "name": "Regulated Rentals", "dataset": "rental_portfolio",
     "source": "PortlandMaps", "color": "#fb923c",
     "source_url": ca.DATASETS["rental_portfolio"]["url"],
     "cmd": f"{EXPORT} python3 pipeline/collect_arcgis.py rental_portfolio",
     "cadence": "quarterly", "hour": 1, "minute": 0, "dow": None, "dom": 1,
     "enabled": True, "continuous": False,
     "what": AB["rental_portfolio"], "why": "Regulated-rental ownership is a landlord/investor signal",
     "note": ""},

    {"id": "businesses", "name": "Business Registry", "dataset": "businesses",
     "source": "Oregon SoS", "color": "#fb923c",
     "source_url": "https://data.oregon.gov/resource/tckn-sxa6",
     "cmd": f"{EXPORT} python3 pipeline/collect_oregon_sos.py",
     "cadence": "quarterly", "hour": 1, "minute": 0, "dow": None, "dom": 1,
     "enabled": True, "continuous": False,
     "what": "Active business registry — entity, status, addresses",
     "why": "Verify entity owners; a dissolved entity on a home is distress", "note": ""},

    {"id": "violations", "name": "Code Violations", "dataset": "violations",
     "source": "PortlandMaps", "color": "#f472b6",
     "source_url": "https://www.portlandmaps.com/api/permit/",
     "cmd": "", "cadence": "continuous", "hour": None, "minute": None,
     "dow": None, "dom": None, "enabled": True, "continuous": True,
     "what": "Per-property code-enforcement cases for every residential parcel",
     "why": "Code violations are the strongest distress signal; no bulk source exists",
     "note": "Rolling refresh (~10-day cycle) via the predictor-violations daemon"},

    {"id": "permit_detail", "name": "Permit Details", "dataset": "permit_detail",
     "source": "PortlandMaps", "color": "#f472b6",
     "source_url": "https://www.portlandmaps.com/api/permit/",
     "cmd": "", "cadence": "continuous", "hour": None, "minute": None,
     "dow": None, "dom": None, "enabled": True, "continuous": True,
     "what": "Per-property building permits captured alongside the violations poll",
     "why": "Per-parcel permit history, refreshed on the same rolling cycle",
     "note": "Runs on the predictor-violations daemon, not a timed job"},
]


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "schedule.json"
    if os.path.exists(out) and "--force" not in sys.argv:
        sys.exit(f"{out} exists; pass --force to reseed (overwrites UI edits).")
    with open(out, "w") as f:
        json.dump({"jobs": JOBS}, f, indent=2)
    print(f"seeded {out} with {len(JOBS)} jobs")


if __name__ == "__main__":
    main()
