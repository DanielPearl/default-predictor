#!/usr/bin/env python3
"""
Data lake storage.

The lake is the immutable, append-only archive of every raw pull ever made,
Hive-partitioned as  <source>/<dataset>/captured_date=<date>/<file>, so the
date is labeled in the path and query engines (DuckDB, dbt) auto-detect it as
a `captured_date` column. Nothing here is ever edited; a new week is a new
partition folder. This is the only copy of each week's point-in-time state and
the raw material everything downstream is rebuilt from.

Backend is the local filesystem today (data/lake/). It is written behind a
tiny put() seam so it can move to DigitalOcean Spaces (S3) later by swapping
one function -- see _put_bytes(). Stdlib only.
"""
import gzip
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAKE_ROOT = Path(os.environ.get("LAKE_ROOT", ROOT / "data" / "lake"))

try:
    from zoneinfo import ZoneInfo
    _PACIFIC = ZoneInfo("America/Los_Angeles")
except Exception:  # noqa: BLE001  (zoneinfo/tzdata missing)
    _PACIFIC = None


def capture_date():
    """Today's date in Portland's timezone. Snapshots are dated by local
    (Pacific) calendar, not UTC, so a Saturday-evening run isn't stamped
    Sunday."""
    now = datetime.now(_PACIFIC) if _PACIFIC else datetime.now(timezone.utc)
    return now.date().isoformat()


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def relpath(source, dataset, captured_date):
    """Hive-style partition path, so the date is labeled in the path and query
    engines auto-detect it as a `captured_date` column:
      <source>/<dataset>/captured_date=<date>/<dataset>.ndjson.gz
    """
    return f"{slug(source)}/{dataset}/captured_date={captured_date}/{dataset}.ndjson.gz"


def _abspath(rel):
    return LAKE_ROOT / rel


def spaces_config():
    """Object-storage config if the lake is backed by DigitalOcean Spaces (S3),
    else None. The mere presence of Secret Keys/do_spaces.json flips the lake
    from the local filesystem to Spaces -- no code change needed."""
    cfg = ROOT / "Secret Keys" / "do_spaces.json"
    if not cfg.exists():
        return None
    try:
        return json.loads(cfg.read_text())
    except Exception:  # noqa: BLE001  (malformed config -> stay local)
        return None


_S3 = None


def _s3_client(cfg):
    global _S3
    if _S3 is None:
        import boto3  # lazy: only needed when the lake is on Spaces
        _S3 = boto3.client(
            "s3", region_name=cfg["region"], endpoint_url=cfg["endpoint"],
            aws_access_key_id=cfg["access_key"], aws_secret_access_key=cfg["secret_key"])
    return _S3


def lake_uri():
    """Base location of the lake for query engines (DuckDB/dbt): an s3:// bucket
    URL when backed by Spaces, else the local folder path."""
    cfg = spaces_config()
    return f"s3://{cfg['bucket']}" if cfg else str(LAKE_ROOT)


def _put_bytes(rel, data: bytes):
    """Write raw bytes into the lake. The ONE seam: local filesystem by default,
    or an S3 put_object into Spaces when Secret Keys/do_spaces.json is present."""
    cfg = spaces_config()
    if cfg:
        ctype = "application/x-ndjson+gzip" if rel.endswith(".gz") else "application/json"
        _s3_client(cfg).put_object(Bucket=cfg["bucket"], Key=rel, Body=data, ContentType=ctype)
        return f"s3://{cfg['bucket']}/{rel}"
    p = _abspath(rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


class RawWriter:
    """Streams records to a gzipped NDJSON file in the lake without holding the
    whole dataset in memory. Use as a context manager; close() returns the
    catalog facts (relpath, rows, bytes, sha256)."""

    def __init__(self, source, dataset, captured_date):
        self.source = source
        self.dataset = dataset
        self.captured_date = captured_date
        self.filename = f"{dataset}.ndjson.gz"
        self.rel = relpath(source, dataset, captured_date)
        self.final = _abspath(self.rel)
        self.part = self.final.with_suffix(self.final.suffix + ".part")
        self.final.parent.mkdir(parents=True, exist_ok=True)
        self._gz = gzip.open(self.part, "wt", encoding="utf-8")
        self.rows = 0

    def write(self, obj):
        self._gz.write(json.dumps(obj, separators=(",", ":")) + "\n")
        self.rows += 1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        try:
            self._gz.close()
        except Exception:  # noqa: BLE001
            pass
        if any(exc):  # error during capture: leave no half-file in place
            self.part.unlink(missing_ok=True)

    def close(self):
        self._gz.close()
        h = hashlib.sha256()
        with open(self.part, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        nbytes = self.part.stat().st_size
        # Collection always streams to a local temp (.part) to keep memory flat;
        # on completion, land it in whatever backs the lake. For Spaces, upload
        # the finished bytes and drop the temp; for local, just rename into place.
        if spaces_config():
            _put_bytes(self.rel, self.part.read_bytes())
            self.part.unlink(missing_ok=True)
        else:
            os.replace(self.part, self.final)
        return {"relpath": self.rel, "rows": self.rows,
                "bytes": nbytes, "sha256": h.hexdigest()}


def write_manifest(source, captured_date, entries):
    """A small human-readable manifest written into each dataset's partition
    folder (next to its data file)."""
    from pathlib import PurePosixPath
    for e in entries:
        rel = e.get("relpath")
        if not rel:
            continue
        mrel = str(PurePosixPath(rel).parent / "_manifest.json")
        body = json.dumps({
            "source": source,
            "captured_date": captured_date,
            "written_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "file": e,
        }, indent=2).encode()
        _put_bytes(mrel, body)
