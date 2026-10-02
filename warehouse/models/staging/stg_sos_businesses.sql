-- Oregon SoS active business registry (entity status / addresses).
select *, regexp_extract(filename, '[0-9]{4}-[0-9]{2}-[0-9]{2}') as captured_date
from read_json_auto('{{ var("lake_path") }}/oregon-sos/*/businesses.ndjson.gz',
                    filename=true, union_by_name=true, ignore_errors=true)
