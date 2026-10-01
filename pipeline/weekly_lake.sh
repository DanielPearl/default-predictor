#!/usr/bin/env bash
# Lake-only weekly capture (run standalone, or let weekly.sh call the collector
# as its first step). Lands the raw PortlandMaps snapshot in the data lake and
# refreshes the site's uploads.json.
#
# Install on the droplet (Sundays 02:00 UTC, an hour before the main job):
#   crontab -e
#   0 2 * * 0  /root/predictor/pipeline/weekly_lake.sh >> /var/log/predictor-lake.log 2>&1
set -e
cd "$(dirname "$0")/.."
echo "[$(date -u +%FT%TZ)] lake capture: PortlandMaps"
EXPORT_UPLOADS=/var/www/default-predictor/uploads.json python3 pipeline/collect_portlandmaps.py
echo "[$(date -u +%FT%TZ)] lake capture complete"
