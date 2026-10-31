# Default Predictor — data platform

A pre-foreclosure / distress-signal data product for Multnomah County, OR. The
edge is catching distress **before** a Notice of Default or foreclosure, by
fusing public signals (ownership, permits, code violations, demolitions,
bankruptcies, business registry) at the parcel level.

## Architecture

```
SOURCES                      LAKE (object storage)          WAREHOUSE (DuckDB)
collectors  ─────────────▶   bronze NDJSON ──▶ silver  ──▶  dbt: staging ─▶ core ─▶ mart
PortlandMaps, PACER,         (raw snapshots)   Parquet
Oregon SoS                   captured_date=…   (lake_parquet)

                 orchestrated + monitored by  Dagster
```

- **Sources → lake.** Python collectors (`pipeline/collect_*.py`) pull each
  source and land immutable, Hive-partitioned snapshots
  (`<source>/<dataset>/captured_date=YYYY-MM-DD/`). Bronze = raw NDJSON.
- **Silver (Parquet).** `pipeline/lake_to_parquet.py` converts the raw NDJSON
  to columnar Parquet — ~20x faster reads, especially from object storage.
- **Warehouse.** dbt (`warehouse/`) transforms the lake into a DuckDB warehouse:
  `staging` (typed views of each source) → `core` (conformed entities:
  property, owner, ownership, assessment, permit, violation, demolition,
  business) → `mart` (`mart_property_week`, the feature/training table).
- **Storage.** The lake lives in **DigitalOcean Spaces** (S3) when
  `Secret Keys/do_spaces.json` is present; otherwise a local folder. This keeps
  durable raw storage separate from compute.
- **Orchestration.** **Dagster** (`orchestration/`) runs every step as an asset
  with full lineage (`collectors → lake_parquet → staging → core → mart`), run
  history, logs, data previews, retries, schedules, and dbt tests surfaced as
  asset checks.

## Local development

```bash
python3.12 -m venv .venv && .venv/bin/pip install -U pip
.venv/bin/pip install dagster dagster-webserver dagster-dbt dbt-core dbt-duckdb duckdb boto3 requests openpyxl

# Dagster UI (pipeline, runs, lineage, schedules)
export DAGSTER_HOME="$(pwd)/orchestration/dagster_home"
.venv/bin/dagster dev -f orchestration/definitions.py        # http://localhost:3000

# Build the warehouse directly
cd warehouse && ../.venv/bin/dbt build --profiles-dir .

# Browse the databases (DuckDB UI over a read-only snapshot)
.venv/bin/python tools/view_db.py                            # http://localhost:4213
```

## Data quality

dbt tests live beside the models (`_core.yml`, `_mart.yml`): primary-key
`not_null`/`unique` on the hub entities, `accepted_values` on derived
categories, and `relationships` (warn) between facts and the parcel hub. They
run on `dbt build` and appear as **asset checks** in Dagster.

## Deployment

See [`deploy/README.md`](deploy/README.md) — systemd units for the Dagster
webserver + daemon (bound to localhost, reached via SSH tunnel), plus the
cron→Dagster cutover table and DigitalOcean Spaces activation steps.

## Layout

```
pipeline/      collectors, lake writer (lake.py), NDJSON→Parquet converter
warehouse/     dbt project (staging / core / mart + tests)
orchestration/ Dagster definitions (assets, schedules, lineage)
tools/         view_db.py (DuckDB UI launcher)
deploy/        systemd units + deploy guide
Secret Keys/   gitignored credentials (do_spaces.json, API keys)
```
