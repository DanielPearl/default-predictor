-- Oregon SoS active business registry from the lake (Parquet silver layer).
select * from {{ lake_read('oregon-sos', 'businesses') }}
