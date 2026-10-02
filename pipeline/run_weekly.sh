#!/usr/bin/env bash
# WEEKLY run (Sundays). Captures only the fast-moving layers -- permits and
# demolitions -- then refreshes the site. Assessor/taxlots are monthly, so the
# site forward-fills them between monthly pulls.
#   cron: 0 3 * * 0  root  /root/predictor/pipeline/run_weekly.sh
set -e
cd "$(dirname "$0")/.."
log() { echo "[$(date -u +%FT%TZ)] $*"; }

log "WEEKLY: capture fast-moving layers (permits, demolitions)"
python3 pipeline/collect_arcgis.py --cadence weekly
log "WEEKLY: refresh site"
bash pipeline/refresh_site.sh
log "weekly run complete"
