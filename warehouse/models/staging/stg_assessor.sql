-- PortlandMaps assessor accounts from the lake (Hive-partitioned; captured_date auto-detected).
select *
from read_json_auto('{{ var("lake_path") }}/portlandmaps/assessor/captured_date=*/*.ndjson.gz',
                    hive_partitioning=true, union_by_name=true, ignore_errors=true)
