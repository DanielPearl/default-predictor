-- Residential building permits from the lake (Parquet silver layer).
select * from {{ lake_read('portlandmaps', 'permits') }}
