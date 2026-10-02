#!/usr/bin/env bash
# QUARTERLY run (1st of Jan/Apr/Jul/Oct). Captures near-static reference layers
# (rental portfolio) that change rarely.
#   cron: 0 1 1 1,4,7,10 *  root  /root/predictor/pipeline/run_quarterly.sh
set -e
cd "$(dirname "$0")/.."
log() { echo "[$(date -u +%FT%TZ)] $*"; }

log "QUARTERLY: capture static reference layers"
python3 pipeline/collect_arcgis.py --cadence quarterly
log "QUARTERLY: Oregon SoS business registry (entity status/address verification)"
python3 pipeline/collect_oregon_sos.py
python3 pipeline/catalog.py export /var/www/default-predictor/uploads.json
log "quarterly run complete"
