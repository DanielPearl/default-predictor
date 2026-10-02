#!/usr/bin/env python3
"""
Data lake storage.

The lake is the immutable, append-only archive of every raw pull ever made,
partitioned as  <source>/<captured_date>/<file>. Nothing here is ever edited;
a new week is a new folder. This is the only copy of each week's point-in-time
state and the raw material everything downstream is rebuilt from.

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


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def relpath(source, captured_date, filename):
    return f"{slug(source)}/{captured_date}/{filename}"


def _abspath(rel):
    return LAKE_ROOT / rel


def _put_bytes(rel, data: bytes):
    """Write raw bytes into the lake. The ONE seam to change for Spaces:
    replace the filesystem write with an S3 put_object(Bucket, Key=rel, Body)."""
    p = _abspath(rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


class RawWriter:
    """Streams records to a gzipped NDJSON file in the lake without holding the
    whole dataset in memory. Use as a context manager; close() returns the
    catalog facts (relpath, rows, bytes, sha256)."""

    def __init__(self, source, dataset, captured_date, filename):
        self.source = source
        self.dataset = dataset
        self.captured_date = captured_date
        self.filename = filename
        self.rel = relpath(source, captured_date, filename)
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
        os.replace(self.part, self.final)
        return {"relpath": self.rel, "rows": self.rows,
                "bytes": nbytes, "sha256": h.hexdigest()}


def write_manifest(source, captured_date, entries):
    """A small human-readable index of what landed in a partition. Merges with
    any existing manifest (keyed by filename) so multiple datasets landing in
    the same partition all appear."""
    rel = relpath(source, captured_date, "_manifest.json")
    files = {}
    p = _abspath(rel)
    if p.exists():
        try:
            for e in json.loads(p.read_text()).get("files", []):
                files[e.get("filename")] = e
        except Exception:  # noqa: BLE001
            pass
    for e in entries:
        files[e.get("filename")] = e
    body = json.dumps({
        "source": source,
        "captured_date": captured_date,
        "written_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": list(files.values()),
    }, indent=2).encode()
    _put_bytes(rel, body)
    return rel
