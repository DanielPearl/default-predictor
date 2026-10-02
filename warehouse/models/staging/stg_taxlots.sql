-- Multnomah taxlots (parcel attributes) from the lake (Hive-partitioned; captured_date auto-detected).
select *
from read_json_auto('{{ var("lake_path") }}/portlandmaps/taxlots/captured_date=*/*.ndjson.gz',
                    hive_partitioning=true, union_by_name=true, ignore_errors=true)
