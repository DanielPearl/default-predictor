-- Per-property code-enforcement cases from the lake (Parquet silver layer).
select * from {{ lake_read('portlandmaps', 'violations') }}
