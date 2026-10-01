-- Lake catalog: one row per raw file landed in the data lake.
-- This is the index behind the website's Uploads tab and the provenance
-- record for everything downstream. Append-only in spirit; a re-run for the
-- same (source, dataset, captured_date) replaces that week's row.
CREATE TABLE IF NOT EXISTS lake_uploads (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  source        TEXT    NOT NULL,            -- e.g. 'PortlandMaps'
  dataset       TEXT    NOT NULL,            -- e.g. 'assessor'
  captured_date TEXT    NOT NULL,            -- ISO date of the weekly snapshot
  filename      TEXT    NOT NULL,            -- e.g. 'assessor.ndjson.gz'
  relpath       TEXT    NOT NULL,            -- path within the lake
  source_url    TEXT,                        -- endpoint the data came from
  content_type  TEXT,                        -- e.g. 'application/x-ndjson+gzip'
  rows          INTEGER,                     -- record count captured
  bytes         INTEGER,                     -- stored (compressed) size
  sha256        TEXT,                        -- checksum of the stored file
  status        TEXT    NOT NULL DEFAULT 'complete',  -- complete | partial | failed
  fetched_at    TEXT    NOT NULL,            -- UTC ISO timestamp of capture
  duration_s    REAL,                        -- how long the pull took
  notes         TEXT,
  UNIQUE (source, dataset, captured_date)
);

CREATE INDEX IF NOT EXISTS ix_lake_uploads_recent
  ON lake_uploads (captured_date DESC, id DESC);
