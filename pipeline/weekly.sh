#!/usr/bin/env bash
# Weekly history-accumulation job (run on the droplet via cron).
# Refreshes the keyless base + fresh event sources, re-applies cached keyed
# enrichment, appends a change-detected snapshot to history.db, and re-exports
# the served table. Keyed features are cached (static); weekly changes come
# from the base (owner/value), county deeds, and the Portland layers.
set -e
cd "$(dirname "$0")/.."
log() { echo "[$(date -u +%FT%TZ)] $*"; }

log "refresh keyless base (242k parcels)"
python3 pipeline/ingest_taxlots.py >/dev/null
log "rebuild enriched sample (same seeded parcels)"
SAMPLE_SIZE="${SAMPLE_SIZE:-250}" python3 pipeline/export_sample.py >/dev/null
python3 pipeline/enrich_sample.py >/dev/null     # keyed PM: cached/static
python3 pipeline/enrich_county.py >/dev/null     # fresh deeds/exemptions
python3 pipeline/enrich_census.py >/dev/null     # cached
python3 pipeline/enrich_portland.py >/dev/null   # fresh historic/demo/rental
python3 pipeline/enrich_bankruptcy.py >/dev/null # cached
log "append this week's scrape to properties + history snapshot"
python3 pipeline/db_table.py append
python3 pipeline/snapshot.py
log "export served table from DB"
python3 pipeline/db_table.py export /var/www/default-predictor/properties_sample.json
log "weekly run complete"
