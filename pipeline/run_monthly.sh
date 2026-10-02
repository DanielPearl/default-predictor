#!/usr/bin/env bash
# MONTHLY run (1st of the month). Captures the slow county data -- assessor and
# taxlots -- that only batch-updates monthly, refreshes the parcel base, then
# refreshes the site so the new base shows immediately.
#   cron: 0 2 1 * *  root  /root/predictor/pipeline/run_monthly.sh
set -e
cd "$(dirname "$0")/.."
log() { echo "[$(date -u +%FT%TZ)] $*"; }

log "MONTHLY: capture assessor snapshot -> lake"
python3 pipeline/collect_portlandmaps.py
log "MONTHLY: capture taxlots -> lake"
python3 pipeline/collect_arcgis.py --cadence monthly
log "MONTHLY: refresh parcel base (taxlots.db)"
python3 pipeline/ingest_taxlots.py >/dev/null
log "MONTHLY: refresh site"
bash pipeline/refresh_site.sh
log "monthly run complete"
