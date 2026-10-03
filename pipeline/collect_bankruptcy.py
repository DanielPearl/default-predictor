#!/usr/bin/env python3
"""
Daily District of Oregon bankruptcy filings (CM/ECF RSS) -> data lake.

Bankruptcy is federal, so PACER/CM-ECF (District of Oregon, 'orb') is the
authoritative source. The court's RSS feed is FREE and gives, per docket entry:
debtor name, case number, chapter, division (Office: 3 = Portland), trustee,
and the event. It carries NO address -- that lives on the paid petition
document -- so this lands the free signal; linking to a property by address is
a later, paid PACER step, and the Portland-division filter + owner-name match
are downstream (not done here: the lake stays raw).

MUST RUN DAILY. The feed is a rolling ~24h window; miss a day and those filings
roll off for good (only paid PACER recovers them). Entries are deduped by RSS
guid in data/bankruptcy_seen.db, so overlapping daily windows never
double-count, and re-running the same day just rebuilds that day's partition:
  pacer-d-oregon/bankruptcy/captured_date=<date>/bankruptcy.ndjson.gz

  python3 pipeline/collect_bankruptcy.py
Env: CAPTURE_DATE, EXPORT_UPLOADS. Stdlib only.
"""
import json
import os
import re
import sqlite3
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import catalog
import lake

SOURCE, DATASET = "PACER (D. Oregon)", "bankruptcy"
FEED = "https://ecf.orb.uscourts.gov/cgi-bin/rss_outside.pl"
ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "bankruptcy_seen.db"

DESC_RE = {
    "type": re.compile(r"Type:\s*(\w+)"),
    "office": re.compile(r"Office:\s*(\d+)"),
    "chapter": re.compile(r"Chapter:\s*(\d+)"),
    "trustee": re.compile(r"Trustee:\s*(.*?)\s*(?:\[|\(|$)"),
}
EVENT_RE = re.compile(r"\[(.*?)\]")


def fetch(retries=5):
    req = urllib.request.Request(FEED, headers={"User-Agent": "default-predictor research"})
    for a in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001  (transient)
            print(f"  retry {a + 1}: {e}", flush=True)
            time.sleep(3 * (a + 1))
    raise RuntimeError("feed fetch failed")


def parse(xml_bytes):
    """Yield one raw dict per <item> in the RSS feed."""
    root = ET.fromstring(xml_bytes)
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        desc = (item.findtext("description") or "").strip()
        parts = title.split(None, 1)                    # "<case_number> <debtor(s)>"
        rec = {
            "guid": (item.findtext("guid") or item.findtext("link") or "").strip(),
            "case_number": parts[0] if parts else "",
            "debtor_name": parts[1].strip() if len(parts) > 1 else "",
            "link": (item.findtext("link") or "").strip(),
            "pub_date": (item.findtext("pubDate") or "").strip(),
            "title": title,
            "description": desc,
        }
        for k, rx in DESC_RE.items():
            m = rx.search(desc)
            rec[k] = m.group(1).strip() if m else None
        em = EVENT_RE.search(desc)
        rec["event"] = em.group(1).strip() if em else None
        yield rec


def cache_conn():
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(CACHE, timeout=60)
    c.execute("CREATE TABLE IF NOT EXISTS entries "
              "(guid TEXT PRIMARY KEY, captured_date TEXT, first_seen TEXT, record TEXT)")
    return c


def main():
    captured_date = os.environ.get("CAPTURE_DATE") or lake.capture_date()
    catalog.migrate()
    t0 = time.time()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"polling {SOURCE} RSS -> lake ({captured_date})", flush=True)

    recs = list(parse(fetch()))
    print(f"  feed entries: {len(recs)}", flush=True)

    cc = cache_conn()
    new = 0
    for rec in recs:
        g = rec["guid"]
        if not g or cc.execute("SELECT 1 FROM entries WHERE guid=?", (g,)).fetchone():
            continue
        cc.execute("INSERT OR IGNORE INTO entries (guid, captured_date, first_seen, record) "
                   "VALUES (?,?,?,?)", (g, captured_date, now, json.dumps(rec)))
        new += 1
    cc.commit()

    # (Re)build today's partition from every entry first seen today -- idempotent,
    # so a second run the same day accumulates instead of overwriting.
    rows = [json.loads(r[0]) for r in cc.execute(
        "SELECT record FROM entries WHERE captured_date=? ORDER BY first_seen", (captured_date,))]
    cc.close()

    if not rows:
        print("  0 entries for today; nothing landed", flush=True)
        return

    writer = lake.RawWriter(SOURCE, DATASET, captured_date)
    for r in rows:
        writer.write(r)
    facts = writer.close()

    dur = round(time.time() - t0, 1)
    filename = f"{DATASET}.ndjson.gz"
    catalog.record_upload(
        source=SOURCE, dataset=DATASET, captured_date=captured_date, filename=filename,
        relpath=facts["relpath"], source_url=FEED, content_type="application/x-ndjson+gzip",
        rows=facts["rows"], bytes=facts["bytes"], sha256=facts["sha256"], status="complete",
        fetched_at=now, duration_s=dur,
        notes=f"CM/ECF RSS (~24h window); {new} new of {len(recs)} feed entries today; "
              f"no address in feed (paid PACER for that)")
    lake.write_manifest(SOURCE, captured_date, [{
        "dataset": DATASET, "filename": filename, "relpath": facts["relpath"],
        "rows": facts["rows"], "bytes": facts["bytes"], "sha256": facts["sha256"], "status": "complete"}])
    print(f"landed {facts['rows']} entries ({new} new today) -> {facts['relpath']} in {dur}s", flush=True)

    export = os.environ.get("EXPORT_UPLOADS")
    if export:
        catalog.export_json(export)


if __name__ == "__main__":
    main()
