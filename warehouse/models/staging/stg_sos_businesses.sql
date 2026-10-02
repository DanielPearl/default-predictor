-- Oregon SoS active business registry from the lake (Hive-partitioned; captured_date auto-detected).
select *
from read_json_auto('{{ var("lake_path") }}/oregon-sos/businesses/captured_date=*/*.ndjson.gz',
                    hive_partitioning=true, union_by_name=true, ignore_errors=true)
