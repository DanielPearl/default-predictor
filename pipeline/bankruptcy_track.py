#!/usr/bin/env python3
"""
Confirmation tracker for owner<->bankruptcy matches.

bankruptcy_candidates.py lists owner name-matches to review on PACER. This
records your decision on each so the match becomes real, standing data:
  * confirmed = same person -> flag that owner's parcel(s)
  * rejected  = different person (name collision) -> ignore
Reviewed cases drop off the candidate queue (never re-reviewed), and confirmed
cases export as the owner_in_bankruptcy feature, keyed on RNO.

Durable store: data/bankruptcy_confirmations.db (SQLite). Decision details are
auto-filled from the current candidate list, so you just pass the case number.

  python3 pipeline/bankruptcy_track.py review                # the outstanding queue
  python3 pipeline/bankruptcy_track.py confirm <case> [--addr "..."] [--note "..."]
  python3 pipeline/bankruptcy_track.py reject  <case> [--note "..."]
  python3 pipeline/bankruptcy_track.py list                  # all decisions
  python3 pipeline/bankruptcy_track.py export [path]         # owner_bankruptcy.json feature
Stdlib only.
"""
import csv
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "bankruptcy_confirmations.db"
CANDIDATES = ROOT / "data" / "bankruptcy_candidates.csv"
DEFAULT_EXPORT = ROOT / "data" / "owner_bankruptcy.json"


def conn():
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS confirmations (
        case_number TEXT PRIMARY KEY, debtor_name TEXT, rnos TEXT, status TEXT,
        confidence TEXT, pacer_address TEXT, site_address TEXT,
        decided_on TEXT, notes TEXT)""")
    return c


def reviewed():
    """Case numbers already decided -- excluded from the candidate queue."""
    c = conn()
    try:
        return {r[0] for r in c.execute("SELECT case_number FROM confirmations")}
    finally:
        c.close()


def _candidate_row(case_number):
    if not CANDIDATES.exists():
        return {}
    with open(CANDIDATES) as f:
        for r in csv.DictReader(f):
            if r.get("case_number") == case_number:
                return r
    return {}


def _decide(case_number, status, addr=None, note=None):
    cand = _candidate_row(case_number)
    if not cand:
        print(f"warning: {case_number} not in current candidate list; recording anyway")
    c = conn()
    try:
        c.execute("""INSERT INTO confirmations
            (case_number, debtor_name, rnos, status, confidence, pacer_address,
             site_address, decided_on, notes) VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(case_number) DO UPDATE SET
              status=excluded.status, pacer_address=excluded.pacer_address,
              decided_on=excluded.decided_on, notes=excluded.notes""",
                  (case_number, cand.get("debtor_name"), cand.get("rnos"), status,
                   cand.get("confidence"), addr, cand.get("site_address"),
                   date.today().isoformat(), note))
        c.commit()
    finally:
        c.close()
    print(f"{status}: {case_number}  {cand.get('debtor_name', '')}  "
          f"parcels={cand.get('rnos', '')}")


def export(path=DEFAULT_EXPORT):
    c = conn()
    rows = c.execute("SELECT * FROM confirmations WHERE status='confirmed'").fetchall()
    c.close()
    feat = []
    for r in rows:
        for rno in (r["rnos"] or "").split(";"):
            if rno:
                feat.append({"rno": rno, "owner_in_bankruptcy": 1,
                             "case_number": r["case_number"],
                             "debtor_name": r["debtor_name"],
                             "confirmed_on": r["decided_on"]})
    Path(path).write_text(json.dumps(feat, indent=2))
    print(f"wrote {path}: {len(feat)} confirmed owner-parcel flag(s)")


def review():
    done = reviewed()
    if not CANDIDATES.exists():
        print("no candidate file yet (run bankruptcy_candidates.py first)")
        return
    with open(CANDIDATES) as f:
        rows = [r for r in csv.DictReader(f) if r.get("case_number") not in done]
    print(f"outstanding to review: {len(rows)}\n")
    for r in rows:
        print(f"  [{r.get('confidence', ''):6}] {r['case_number']:16} "
              f"{r['debtor_name'][:26]:26} {r.get('site_address', '')[:38]}")
        print(f"            {r.get('pacer_link', '')}")


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "review"

    def opt(name):
        return args[args.index(name) + 1] if name in args else None

    if cmd == "review":
        review()
    elif cmd in ("confirm", "reject"):
        if len(args) < 2:
            sys.exit(f"usage: bankruptcy_track.py {cmd} <case_number>")
        _decide(args[1], "confirmed" if cmd == "confirm" else "rejected",
                addr=opt("--addr"), note=opt("--note"))
    elif cmd == "list":
        c = conn()
        for r in c.execute("SELECT * FROM confirmations ORDER BY decided_on DESC, case_number"):
            print(f"  {r['decided_on']}  {r['status']:9} {r['case_number']:16} "
                  f"{r['debtor_name'] or ''}  [{r['confidence'] or ''}]")
        c.close()
    elif cmd == "export":
        export(args[1] if len(args) > 1 else DEFAULT_EXPORT)
    else:
        sys.exit(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
