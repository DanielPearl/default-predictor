#!/usr/bin/env python3
"""
One-off: migrate the lake from the old flat layout
    <source>/<date>/<dataset>.ndjson.gz
to Hive-style partitioning
    <source>/<dataset>/captured_date=<date>/<dataset>.ndjson.gz
and repoint the catalog's relpath column at the new files.

Idempotent: files already in the new layout are left alone; re-running is safe.
Run once on local and once on the droplet.

    python3 pipeline/migrate_to_hive.py          # do it
    python3 pipeline/migrate_to_hive.py --dry     # show what would move
"""
import re
import sys
from pathlib import Path

import catalog
import lake

LAKE = lake.LAKE_ROOT
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def main():
    dry = "--dry" in sys.argv
    moves = []
    # old layout: <source>/<YYYY-MM-DD>/<dataset>.ndjson.gz
    for src_dir in sorted(p for p in LAKE.iterdir() if p.is_dir()):
        for date_dir in sorted(p for p in src_dir.iterdir() if p.is_dir()):
            if not DATE_RE.match(date_dir.name):
                continue  # already a dataset dir (new layout) -> skip
            captured_date = date_dir.name
            for f in sorted(date_dir.glob("*.ndjson.gz")):
                dataset = f.name[: -len(".ndjson.gz")]
                dest = LAKE / lake.relpath(_unslug(src_dir.name), dataset, captured_date)
                moves.append((f, dest))

    for src, dest in moves:
        print(f"{src.relative_to(LAKE)}  ->  {dest.relative_to(LAKE)}")
        if dry:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        src.replace(dest)

    if dry:
        print(f"\n[dry] {len(moves)} file(s) would move")
        return

    # drop now-empty old date folders (and stale per-date _manifest.json)
    for src_dir in (p for p in LAKE.iterdir() if p.is_dir()):
        for date_dir in list(p for p in src_dir.iterdir() if p.is_dir()):
            if not DATE_RE.match(date_dir.name):
                continue
            for leftover in date_dir.glob("_manifest.json"):
                leftover.unlink()
            if not any(date_dir.iterdir()):
                date_dir.rmdir()

    # repoint the catalog at the new relpaths + rewrite per-partition manifests
    catalog.migrate()
    fixed = 0
    by_src_date = {}
    for row in catalog.list_uploads():
        new_rel = lake.relpath(row["source"], row["dataset"], row["captured_date"])
        if row["relpath"] != new_rel:
            catalog.record_upload(
                source=row["source"], dataset=row["dataset"],
                captured_date=row["captured_date"], filename=f"{row['dataset']}.ndjson.gz",
                relpath=new_rel, source_url=row.get("source_url"),
                content_type=row.get("content_type"), rows=row.get("rows"),
                bytes=row.get("bytes"), sha256=row.get("sha256"),
                status=row.get("status"), fetched_at=row.get("fetched_at"),
                duration_s=row.get("duration_s"), notes=row.get("notes"))
            fixed += 1
        by_src_date.setdefault((row["source"], row["captured_date"]), []).append({
            "dataset": row["dataset"], "filename": f"{row['dataset']}.ndjson.gz",
            "relpath": new_rel, "rows": row.get("rows"), "bytes": row.get("bytes"),
            "sha256": row.get("sha256"), "status": row.get("status")})

    for (source, captured_date), entries in by_src_date.items():
        lake.write_manifest(source, captured_date, entries)

    print(f"\nmoved {len(moves)} file(s); repointed {fixed} catalog row(s)")


def _unslug(dirname):
    """Catalog stores source as a display name ('PortlandMaps', 'Oregon SoS');
    the lake dir is its slug. Map the two known slugs back so relpath() slugs
    to the same dir."""
    return {"portlandmaps": "PortlandMaps", "oregon-sos": "Oregon SoS"}.get(dirname, dirname)


if __name__ == "__main__":
    main()
