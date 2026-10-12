#!/usr/bin/env python3
"""
Emit schedule.json -- what the pipeline is scheduled to download, and when.

Mirrors the installed cron and each runner's collectors so the site's Schedule
page shows the real plan. Blurbs for the ArcGIS layers come straight from
collect_arcgis.DATASETS so they can't drift from the collectors.

    python3 pipeline/schedule.py [out.json]      # default: schedule.json
"""
import json
import sys

import collect_arcgis as ca

AB = {k: v["about"] for k, v in ca.DATASETS.items()}  # dataset -> description

SCHEDULE = {
    "cadences": [
        {"id": "daily", "label": "Daily", "color": "#58a6ff",
         "cron": "0 11 * * *", "freq": "Every day", "runner": "run_daily.sh",
         "captures": [
             {"source": "PACER (D. Oregon)", "dataset": "bankruptcy",
              "what": "New bankruptcy filings — debtor, case, chapter, division (RSS feed)",
              "why": "Owner bankruptcy is a pre-foreclosure life event",
              "note": "The RSS feed is a rolling ~24h window, so this must run daily"}]},
        {"id": "weekly", "label": "Weekly", "color": "#2dd4bf",
         "cron": "0 3 * * 0", "freq": "Every Sunday", "runner": "run_weekly.sh",
         "captures": [
             {"source": "PortlandMaps", "dataset": "permits", "what": AB["permits"],
              "why": "Permit activity (or its absence) signals investment vs neglect"},
             {"source": "PortlandMaps", "dataset": "demolitions", "what": AB["demolitions"],
              "why": "Demolition filings flag distress and redevelopment"}]},
        {"id": "monthly", "label": "Monthly", "color": "#a78bfa",
         "cron": "0 2 1 * *", "freq": "1st of each month", "runner": "run_monthly.sh",
         "captures": [
             {"source": "PortlandMaps", "dataset": "assessor",
              "what": "County assessor roll — owner, value, sale, legal, location",
              "why": "Core property, ownership, and the 3-year value trend"},
             {"source": "PortlandMaps", "dataset": "taxlots", "what": AB["taxlots"],
              "why": "Parcel base; owner mailing vs site address (absentee flag)"}]},
        {"id": "quarterly", "label": "Quarterly", "color": "#fb923c",
         "cron": "0 1 1 1,4,7,10 *", "freq": "1st of Jan, Apr, Jul, Oct",
         "runner": "run_quarterly.sh",
         "captures": [
             {"source": "PortlandMaps", "dataset": "rental_portfolio", "what": AB["rental_portfolio"],
              "why": "Regulated-rental ownership is a landlord/investor signal"},
             {"source": "Oregon SoS", "dataset": "businesses",
              "what": "Active business registry — entity, status, addresses",
              "why": "Verify entity owners; a dissolved entity on a home is distress"}]},
        {"id": "continuous", "label": "Continuous", "color": "#f472b6",
         "cron": None, "freq": "Rolling refresh (~10-day cycle)",
         "runner": "predictor-violations (daemon)",
         "captures": [
             {"source": "PortlandMaps", "dataset": "violations",
              "what": "Per-property code-enforcement cases for every residential parcel",
              "why": "Code violations are the strongest distress signal; no bulk source exists",
              "note": "Each property is re-polled as its data ages past the refresh window, so new cases keep flowing in (~10 days for a full pass at 200 req / 15 min)"},
             {"source": "PortlandMaps", "dataset": "permit_detail",
              "what": "Per-property building permits captured alongside the violations poll",
              "why": "Per-parcel permit history, refreshed on the same rolling cycle"}]},
    ],
    "backfills": [],
}


NAMES = {
    "bankruptcy": "Bankruptcy Filings", "permits": "Building Permits",
    "demolitions": "Demolition Permits", "assessor": "Assessor Roll",
    "taxlots": "Taxlots", "rental_portfolio": "Regulated Rentals",
    "businesses": "Business Registry", "violations": "Code Violations",
    "permit_detail": "Permit Details",
}

# Where each dataset actually comes from (the live endpoint we pull).
URLS = {
    "bankruptcy": "https://ecf.orb.uscourts.gov/cgi-bin/rss_outside.pl",
    "assessor": "https://www.portlandmaps.com/api/assessor/",
    "businesses": "https://data.oregon.gov/resource/tckn-sxa6",
    "violations": "https://www.portlandmaps.com/api/permit/",
    "permit_detail": "https://www.portlandmaps.com/api/permit/",
    "permits": ca.DATASETS["permits"]["url"],
    "demolitions": ca.DATASETS["demolitions"]["url"],
    "taxlots": ca.DATASETS["taxlots"]["url"],
    "rental_portfolio": ca.DATASETS["rental_portfolio"]["url"],
}


def main():
    for c in SCHEDULE["cadences"]:
        for cap in c["captures"]:
            cap["name"] = NAMES.get(cap["dataset"], cap["dataset"].replace("_", " ").title())
            cap["source_url"] = URLS.get(cap["dataset"], "")
    out = sys.argv[1] if len(sys.argv) > 1 else "schedule.json"
    with open(out, "w") as f:
        json.dump(SCHEDULE, f, indent=2)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
