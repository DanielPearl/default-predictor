-- PortlandMaps assessor accounts from the lake (Parquet silver layer).
select * from {{ lake_read('portlandmaps', 'assessor') }}
