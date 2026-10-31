-- Multnomah taxlots (parcel attributes) from the lake (Parquet silver layer).
select * from {{ lake_read('portlandmaps', 'taxlots') }}
