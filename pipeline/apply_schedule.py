#!/usr/bin/env python3
"""
Generate and install the droplet crontab from schedule.json.

schedule.json is the source of truth (edited via the UI). This turns each
enabled, non-continuous job into a cron line. Times are LOCAL (the droplet's
timezone is America/Los_Angeles), so a job shown as "4:00 AM daily" fires at
4:00 AM Pacific. Continuous jobs (violations/permit_detail) run under the
predictor-violations systemd daemon and get no cron line. A daily maintenance
line rebuilds the served site.

Run it after any edit to schedule.json (the API does this automatically).

    python3 pipeline/apply_schedule.py            # install
    python3 pipeline/apply_schedule.py --dry      # print only
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "schedule.json"
HEADER = "# Default Predictor scheduler -- generated from schedule.json; edit via the UI, not here"


def cron_fields(j):
    mn, hr, cad = j.get("minute", 0), j.get("hour", 0), j["cadence"]
    if cad == "daily":
        return f"{mn} {hr} * * *"
    if cad == "weekly":
        return f"{mn} {hr} * * {j['dow']}"
    if cad == "monthly":
        return f"{mn} {hr} {j['dom']} * *"
    if cad == "quarterly":
        return f"{mn} {hr} {j['dom']} 1,4,7,10 *"
    return None


def build():
    cfg = json.loads(CFG.read_text())
    lines = ["PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", HEADER]
    for j in cfg.get("jobs", []):
        if j.get("continuous") or not j.get("enabled"):
            continue
        f = cron_fields(j)
        if f:
            lines.append(f"{f}  cd {ROOT} && {j['cmd']} >> data/sched-{j['id']}.log 2>&1")
    lines.append(f"0 5 * * *  cd {ROOT} && bash pipeline/refresh_site.sh >> data/refresh.log 2>&1")
    return "\n".join(lines) + "\n"


def main():
    tab = build()
    if "--dry" in sys.argv:
        print(tab)
        return
    subprocess.run(["crontab", "-"], input=tab, text=True, check=True)
    print("installed crontab:\n" + tab)


if __name__ == "__main__":
    main()
