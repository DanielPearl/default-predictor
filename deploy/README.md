# Deploying the Dagster orchestration layer to the droplet

Turnkey steps. Nothing here runs automatically -- you run it on the droplet when
you're ready. The design keeps Dagster **private** (bound to localhost, reached
by SSH tunnel) and lets Dagster and cron run **in parallel** until you cut over.

Assumes the project lives at `/root/predictor` on the droplet (as the cron
runners do). Adjust paths if different.

## 1. Get the code + a modern Python venv on the droplet

```bash
cd /root/predictor
git pull                                   # or rsync your working copy up
python3.12 -m venv .venv                   # install python@3.12 first if needed
.venv/bin/pip install --upgrade pip
.venv/bin/pip install dagster dagster-webserver dagster-dbt \
                      dbt-core==1.10.23 dbt-duckdb==1.10.0 duckdb==1.4.5 boto3 requests openpyxl
```

## 2. Prepare Dagster + dbt state

```bash
mkdir -p /root/predictor/orchestration/dagster_home
printf '# empty = defaults\n' > /root/predictor/orchestration/dagster_home/dagster.yaml
cd /root/predictor/warehouse && ../.venv/bin/dbt parse --profiles-dir .   # generates target/manifest.json
```

## 3. Install the systemd services

```bash
cp /root/predictor/deploy/dagster-webserver.service /etc/systemd/system/
cp /root/predictor/deploy/dagster-daemon.service    /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now dagster-webserver dagster-daemon
systemctl status dagster-webserver dagster-daemon   # confirm both active
```

## 4. View the UI (private, via SSH tunnel)

From your laptop:

```bash
ssh -L 3000:localhost:3000 root@<droplet-ip>
# then open http://localhost:3000
```

The webserver binds to `127.0.0.1:3000`, so it is never exposed publicly.

## 5. Cut over from cron -- one job at a time

Schedules ship **STOPPED**. For each job, once you trust it:

1. In the Dagster UI (Automation tab), start that schedule.
2. Remove or comment the matching line in the droplet crontab (`crontab -e`),
   so the job isn't run twice.

Mapping (cron runner -> Dagster schedule):

| cron | Dagster schedule |
|------|------------------|
| `run_daily.sh` (bankruptcy)        | `daily_ingest_schedule` (4:00 AM PT) |
| `run_weekly.sh` (permits, demo)    | `weekly_ingest_schedule` (Sun 3:00 AM) |
| `run_monthly.sh` (assessor, taxlots) | `monthly_ingest_schedule` (1st, 2:00 AM) |
| quarterly (rentals, businesses)    | `quarterly_ingest_schedule` |
| (none yet -- warehouse was manual) | `dbt_build_schedule` (5:30 AM PT) |

`refresh_site.sh` / `ingest_taxlots.py` are **not** yet Dagster assets -- keep
their cron lines until they're wrapped in a later step.

## 6. Database viewer on the droplet (optional)

```bash
.venv/bin/python tools/view_db.py          # starts the DuckDB UI on :4213
ssh -L 4213:localhost:4213 root@<droplet-ip>   # from your laptop, then open :4213
```

---

# Activating DigitalOcean Spaces for the lake (storage off compute)

Your `pipeline/lake.py` already supports Spaces -- it switches from the local
filesystem to S3 **the moment** `Secret Keys/do_spaces.json` exists. No code
change needed. Steps:

1. In DigitalOcean: create a **Space** (object storage bucket) and generate a
   **Spaces access key** (Access Key + Secret).
2. Create `Secret Keys/do_spaces.json` (see `do_spaces.json.example`):

   ```json
   {
     "bucket": "your-space-name",
     "region": "nyc3",
     "endpoint": "https://nyc3.digitaloceanspaces.com",
     "access_key": "...",
     "secret_key": "..."
   }
   ```

3. Migrate the existing local lake up to Spaces (one-off):

   ```bash
   .venv/bin/python pipeline/lake_to_spaces.py
   ```

4. Point dbt at the Spaces lake so the warehouse reads from S3:

   ```bash
   export DBT_LAKE_PATH="s3://your-space-name"
   ```

   and add an httpfs S3 secret to `warehouse/profiles.yml` (DuckDB) so it can
   read `s3://` -- region/endpoint/key/secret matching the JSON above.

5. From then on, every collector writes raw snapshots to Spaces automatically;
   the droplet keeps only compute + the DuckDB warehouse. Keep a few local
   captures until you've confirmed Spaces reads/writes end to end.
