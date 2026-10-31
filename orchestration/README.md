# orchestration/ — Dagster (step 1)

An **additive** orchestration + monitoring layer over the existing pipeline.
Nothing in `pipeline/` changed: each Dagster asset shells out to the existing
collector exactly as cron does, then reads the lake manifest to show row counts
and a data preview in the UI.

## Status: step 1

- Wraps **one** collector so far: `bankruptcy_filings` → `pipeline/collect_bankruptcy.py`.
- A daily schedule (4:00 AM Pacific) exists but ships **STOPPED**. cron still runs
  everything. Nothing fires from Dagster until you start the schedule in the UI.

## Run locally

```bash
export DAGSTER_HOME="$(pwd)/orchestration/dagster_home"
.venv/bin/dagster dev -f orchestration/definitions.py
# open http://localhost:3000
```

In the UI: **Assets → bankruptcy_filings → Materialize** runs the collector; the
run shows logs, and the asset shows `rows`, `captured_date`, and a `preview`
sample. "Runs" lists every execution with status and logs.

## On the droplet (later step)

Run `dagster-webserver` + `dagster-daemon` under systemd, reach the UI over an
SSH tunnel (no public exposure, no auth to manage):

```bash
ssh -L 3000:localhost:3000 your-user@your-droplet
```

## Cutover discipline

Run Dagster and cron in parallel until trusted. Only then: disable the cron line
for a job and set that job's Dagster schedule to RUNNING. One scheduler per job,
never both.
