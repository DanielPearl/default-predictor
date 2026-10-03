#!/usr/bin/env bash
# DAILY run. Polls the District of Oregon bankruptcy CM/ECF RSS feed -- a
# rolling ~24h window, so missing a day loses those filings for good (only paid
# PACER recovers them). This MUST run every day. Dedup is by RSS guid, so
# re-running is safe; it lands one Hive partition per day and refreshes the
# Uploads catalog.
#   cron: 0 11 * * *  root  /root/predictor/pipeline/run_daily.sh   (11:00 UTC = 4am PT)
set -e
cd "$(dirname "$0")/.."
log() { echo "[$(date -u +%FT%TZ)] $*"; }

log "DAILY: District of Oregon bankruptcy filings (CM/ECF RSS)"
python3 pipeline/collect_bankruptcy.py
python3 pipeline/catalog.py export /var/www/default-predictor/uploads.json
log "daily run complete"
