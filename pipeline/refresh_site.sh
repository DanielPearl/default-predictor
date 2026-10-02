#!/usr/bin/env bash
# Rebuild the enriched sample, append a change-detected history snapshot, and
# re-export what the website serves (Properties, Defaults, Uploads). Called by
# the weekly and monthly runners after their captures. Uses whatever parcel
# base (taxlots.db) exists -- that base is refreshed monthly.
set -e
cd "$(dirname "$0")/.."
log() { echo "[$(date -u +%FT%TZ)] $*"; }

log "rebuild enriched sample (same seeded parcels)"
SAMPLE_SIZE="${SAMPLE_SIZE:-250}" python3 pipeline/export_sample.py >/dev/null
python3 pipeline/enrich_sample.py >/dev/null     # keyed PM: cached/static
python3 pipeline/enrich_county.py >/dev/null     # fresh deeds/exemptions
python3 pipeline/enrich_census.py >/dev/null     # cached
python3 pipeline/enrich_portland.py >/dev/null   # fresh historic/demo/rental
python3 pipeline/enrich_bankruptcy.py >/dev/null # cached
log "append scrape to properties + history snapshot"
python3 pipeline/db_table.py append
python3 pipeline/snapshot.py
log "export served table + defaults + uploads"
python3 pipeline/db_table.py export /var/www/default-predictor/properties_sample.json
python3 pipeline/score_defaults.py /var/www/default-predictor/properties_sample.json /var/www/default-predictor/defaults.json
python3 pipeline/catalog.py export /var/www/default-predictor/uploads.json
log "site refresh complete"
