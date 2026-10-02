-- Multnomah taxlots (parcel attributes) from the lake.
select *, regexp_extract(filename, '[0-9]{4}-[0-9]{2}-[0-9]{2}') as captured_date
from read_json_auto('{{ var("lake_path") }}/portlandmaps/*/taxlots.ndjson.gz',
                    filename=true, union_by_name=true, ignore_errors=true)
