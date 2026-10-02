-- Per-property code-enforcement cases (from the violations backfill).
select *, regexp_extract(filename, '[0-9]{4}-[0-9]{2}-[0-9]{2}') as captured_date
from read_json_auto('{{ var("lake_path") }}/portlandmaps/*/violations.ndjson.gz',
                    filename=true, union_by_name=true, ignore_errors=true)
