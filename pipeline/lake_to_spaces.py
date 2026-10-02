#!/usr/bin/env python3
"""
One-time: upload the existing local lake files into DigitalOcean Spaces.

New captures land in Spaces automatically once Secret Keys/do_spaces.json
exists (lake.py routes writes there). This pushes the dumps already on local
disk up to the Space, keyed by their lake relpath, so the Space is complete.
Run it on whatever machine holds the files (the droplet for production).

Idempotent: re-running overwrites with identical bytes. Keeps the local copies
in place -- delete them yourself once you've confirmed the Space is good.

    python3 pipeline/lake_to_spaces.py
    python3 pipeline/lake_to_spaces.py --dry
"""
import sys

import lake


def main():
    dry = "--dry" in sys.argv
    cfg = lake.spaces_config()
    if not cfg:
        raise SystemExit("No Secret Keys/do_spaces.json -- create the Space + key first.")
    root = lake.LAKE_ROOT
    files = [f for f in sorted(root.rglob("*")) if f.is_file()]
    n = total = 0
    for f in files:
        rel = str(f.relative_to(root))
        total += f.stat().st_size
        print(f"  {'[dry] ' if dry else ''}{rel}  ({f.stat().st_size/1e6:.2f} MB)")
        if not dry:
            lake._put_bytes(rel, f.read_bytes())
            n += 1
    where = f"s3://{cfg['bucket']}"
    print(f"\n{'would upload' if dry else 'uploaded'} {len(files) if dry else n} files "
          f"({total/1e6:.1f} MB) to {where}")


if __name__ == "__main__":
    main()
