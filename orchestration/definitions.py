"""
Dagster definitions for Default Predictor.

ADDITIVE orchestration layer -- it does not change existing pipeline code. Each
ingestion asset shells out to the existing collector exactly as cron does, then
reads the lake manifest to surface row counts + a data preview in the UI. The
warehouse/ dbt project is pulled in as assets via dagster-dbt.

cron still owns scheduling for now -- every schedule below ships STOPPED, so
nothing fires from Dagster until you start it in the UI. Run both in parallel,
trust Dagster, then disable the matching cron line and start the schedule.

Local run:
    export DAGSTER_HOME="$(pwd)/orchestration/dagster_home"
    .venv/bin/dagster dev -f orchestration/definitions.py
    # then open http://localhost:3000  (on the droplet: reach it via SSH tunnel)
"""
import gzip
import json
import os
import subprocess
import sys
from pathlib import Path

from dagster import (
    AssetKey,
    Backoff,
    Definitions,
    DefaultScheduleStatus,
    MaterializeResult,
    MetadataValue,
    RetryPolicy,
    ScheduleDefinition,
    asset,
    define_asset_job,
)
from dagster_dbt import DagsterDbtTranslator, DbtCliResource, dbt_assets

ROOT = Path(__file__).resolve().parents[1]
LAKE = ROOT / "data" / "lake"
DBT_DIR = ROOT / "warehouse"
DBT_MANIFEST = DBT_DIR / "target" / "manifest.json"
# dbt executable that ships in the same venv as the running interpreter
# (portable: resolves to .venv/bin/dbt here and on the droplet alike).
DBT_EXE = str(Path(sys.executable).with_name("dbt"))
PY = sys.executable
TZ = "America/Los_Angeles"
# External APIs are flaky (e.g. PortlandMaps paging giving up mid-pull), so give
# every ingestion/convert step a few exponential-backoff retries.
RETRY = RetryPolicy(max_retries=3, delay=30, backoff=Backoff.EXPONENTIAL)


def _activate_spaces_for_dbt():
    """If the lake is on Spaces (do_spaces.json present), point dbt at the bucket
    and expose the creds DuckDB's httpfs S3 secret reads. Collectors already route
    to Spaces via lake.py; this keeps dbt reading the same place. No-op locally."""
    cfg_path = ROOT / "Secret Keys" / "do_spaces.json"
    if not cfg_path.exists():
        return
    try:
        cfg = json.loads(cfg_path.read_text())
    except Exception:  # noqa: BLE001  (malformed -> stay local)
        return
    os.environ.setdefault("DBT_LAKE_PATH", f"s3://{cfg['bucket']}")
    os.environ.setdefault("DO_SPACES_KEY", cfg["access_key"])
    os.environ.setdefault("DO_SPACES_SECRET", cfg["secret_key"])


_activate_spaces_for_dbt()


# --------------------------------------------------------------------------
# Shared helpers: find the newest lake partition, pull rows + a preview
# --------------------------------------------------------------------------
def _latest_partition(dataset: str):
    """Newest captured_date=* dir for a dataset, regardless of source slug."""
    parts = sorted(LAKE.glob(f"*/{dataset}/captured_date=*"))
    return parts[-1] if parts else None


def _manifest_rows(part: Path, dataset: str):
    man = part / "_manifest.json"
    if not man.exists():
        return None
    m = json.loads(man.read_text())
    files = m.get("files") or ([m["file"]] if "file" in m else [])
    for f in files:
        if f.get("dataset") == dataset:
            return f.get("rows")
    return None


def _sample_raw(gz: Path, n: int = 3):
    out = []
    if gz.exists():
        with gzip.open(gz, "rt") as fh:
            for i, line in enumerate(fh):
                if i >= n:
                    break
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return out


def _collect_metadata(part: Path, dataset: str, stdout: str) -> dict:
    meta = {}
    tail = (stdout or "").strip()[-1500:]
    if tail:
        meta["log_tail"] = MetadataValue.md("```\n" + tail + "\n```")
    if part:
        meta["captured_date"] = part.name.split("=")[-1]
        rows = _manifest_rows(part, dataset)
        if rows is not None:
            meta["rows"] = MetadataValue.int(rows)
        gz = part / f"{dataset}.ndjson.gz"
        if gz.exists():
            meta["lake_file"] = MetadataValue.path(str(gz))
            meta["preview"] = MetadataValue.json({"sample": _sample_raw(gz)})
    return meta


def _run_collector(context, argv: list[str], dataset: str, extra_env: dict | None = None):
    env = {**os.environ, **(extra_env or {})}
    proc = subprocess.run(
        [PY, *argv], cwd=str(ROOT), capture_output=True, text=True, env=env,
    )
    if proc.stdout:
        context.log.info(proc.stdout)
    if proc.returncode != 0:
        context.log.error(proc.stderr or "(no stderr)")
        raise RuntimeError(f"{' '.join(argv)} exited {proc.returncode}")
    return MaterializeResult(metadata=_collect_metadata(_latest_partition(dataset), dataset, proc.stdout))


# --------------------------------------------------------------------------
# Ingestion assets -- each wraps an existing collector, unchanged
# --------------------------------------------------------------------------
# name, dataset, argv (after python), source group, description
COLLECTORS = [
    ("bankruptcy", "bankruptcy", ["pipeline/collect_bankruptcy.py"], "pacer",
     "Daily D. Oregon bankruptcy filings (CM/ECF RSS). Deduped by RSS guid."),
    ("permits", "permits", ["pipeline/collect_arcgis.py", "permits"], "portlandmaps",
     "Building permits (ArcGIS feature service) -> lake."),
    ("demolitions", "demolitions", ["pipeline/collect_arcgis.py", "demolitions"], "portlandmaps",
     "Demolition permits (ArcGIS feature service) -> lake."),
    ("taxlots", "taxlots", ["pipeline/collect_arcgis.py", "taxlots"], "portlandmaps",
     "Taxlots parcel base (ArcGIS feature service) -> lake."),
    ("rental_portfolio", "rental_portfolio", ["pipeline/collect_arcgis.py", "rental_portfolio"], "portlandmaps",
     "Regulated rental portfolio (ArcGIS feature service) -> lake."),
    ("assessor", "assessor", ["pipeline/collect_portlandmaps.py"], "portlandmaps",
     "County assessor roll (PortlandMaps API) -> lake."),
    ("businesses", "businesses", ["pipeline/collect_oregon_sos.py"], "oregon_sos",
     "Active business registry (Oregon Secretary of State) -> lake."),
]


def _make_collector_asset(name, dataset, argv, group, desc):
    @asset(name=name, group_name=group, compute_kind="python", description=desc,
           retry_policy=RETRY)
    def _a(context) -> MaterializeResult:
        return _run_collector(context, argv, dataset)
    return _a


collector_assets = {
    name: _make_collector_asset(name, dataset, argv, group, desc)
    for (name, dataset, argv, group, desc) in COLLECTORS
}


@asset(
    name="violations_permit_detail", group_name="portlandmaps", compute_kind="python",
    retry_policy=RETRY,
    description="Per-parcel code violations + permit details (PortlandMaps). Normally a "
                "continuous rolling refresh; here one pass per run via ONCE=1. Heavy -- "
                "iterates many parcels, so schedule deliberately.",
)
def violations_permit_detail(context) -> MaterializeResult:
    return _run_collector(context, ["pipeline/collect_violations.py"], "violations",
                          extra_env={"ONCE": "1"})


# --------------------------------------------------------------------------
# Parquet silver layer: convert raw NDJSON (bronze) -> Parquet that dbt reads
# (~20x faster, especially from Spaces). Depends on every collector.
# --------------------------------------------------------------------------
@asset(
    name="lake_parquet", group_name="warehouse", compute_kind="duckdb",
    retry_policy=RETRY,
    deps=[*collector_assets.values(), violations_permit_detail],
    description="Build the lake's Parquet silver layer from the raw NDJSON. dbt "
                "staging reads Parquet, which is ~20x faster than gzipped JSON, "
                "especially over Spaces. Wraps pipeline/lake_to_parquet.py.",
)
def lake_parquet(context) -> MaterializeResult:
    proc = subprocess.run(
        [PY, "pipeline/lake_to_parquet.py"], cwd=str(ROOT), capture_output=True, text=True,
    )
    if proc.stdout:
        context.log.info(proc.stdout)
    if proc.returncode != 0:
        context.log.error(proc.stderr or "(no stderr)")
        raise RuntimeError(f"lake_to_parquet.py exited {proc.returncode}")
    tail = (proc.stdout or "").strip()[-1500:]
    return MaterializeResult(
        metadata={"log_tail": MetadataValue.md("```\n" + tail + "\n```")} if tail else {})


# --------------------------------------------------------------------------
# Warehouse: the existing dbt project as assets (staging -> core -> mart)
# --------------------------------------------------------------------------
class LakeLinkTranslator(DagsterDbtTranslator):
    """Make every dbt staging model depend on the Parquet layer, so lineage flows
    collectors -> lake_parquet -> stg_* -> core_* -> mart (no dbt SQL changes)."""

    def get_asset_spec(self, manifest, unique_id, project):
        spec = super().get_asset_spec(manifest, unique_id, project)
        name = manifest.get("nodes", {}).get(unique_id, {}).get("name") or ""
        if name.startswith("stg_"):
            spec = spec.merge_attributes(deps=[AssetKey("lake_parquet")])
        return spec


@dbt_assets(manifest=DBT_MANIFEST, dagster_dbt_translator=LakeLinkTranslator())
def dbt_warehouse(context, dbt: DbtCliResource):
    """The warehouse/ dbt project. `dbt build` reads the lake and (re)builds
    data/warehouse.duckdb, running model tests along the way."""
    yield from dbt.cli(["build"], context=context).stream()


# --------------------------------------------------------------------------
# Jobs + schedules, by cadence (mirror the cron runners). All STOPPED.
# --------------------------------------------------------------------------
def _sched(name, job, cron):
    return ScheduleDefinition(
        name=name, job=job, cron_schedule=cron, execution_timezone=TZ,
        default_status=DefaultScheduleStatus.STOPPED,
    )


daily_job = define_asset_job("daily_ingest", selection=[collector_assets["bankruptcy"]])
weekly_job = define_asset_job(
    "weekly_ingest", selection=[collector_assets["permits"], collector_assets["demolitions"]])
monthly_job = define_asset_job(
    "monthly_ingest", selection=[collector_assets["taxlots"], collector_assets["assessor"]])
quarterly_job = define_asset_job(
    "quarterly_ingest", selection=[collector_assets["rental_portfolio"], collector_assets["businesses"]])
dbt_build_job = define_asset_job("dbt_build", selection=[lake_parquet, dbt_warehouse])

schedules = [
    _sched("daily_ingest_schedule", daily_job, "0 4 * * *"),         # 4:00 AM PT
    _sched("weekly_ingest_schedule", weekly_job, "0 3 * * 0"),       # Sun 3:00 AM PT
    _sched("monthly_ingest_schedule", monthly_job, "0 2 1 * *"),     # 1st, 2:00 AM PT
    _sched("quarterly_ingest_schedule", quarterly_job, "0 1 1 1,4,7,10 *"),  # Jan/Apr/Jul/Oct 1st
    _sched("dbt_build_schedule", dbt_build_job, "30 5 * * *"),       # 5:30 AM PT, after collectors
]

defs = Definitions(
    assets=[*collector_assets.values(), violations_permit_detail, lake_parquet, dbt_warehouse],
    jobs=[daily_job, weekly_job, monthly_job, quarterly_job, dbt_build_job],
    schedules=schedules,
    resources={
        "dbt": DbtCliResource(
            project_dir=str(DBT_DIR), profiles_dir=str(DBT_DIR), dbt_executable=DBT_EXE,
        ),
    },
)
