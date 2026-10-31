{% macro lake_read(source, dataset) %}
{#- Read one dataset from the lake. Default = the Parquet silver layer (fast,
    especially from Spaces). Set var lake_format=ndjson to read the raw bronze
    NDJSON instead (e.g. before the Parquet layer has been built). lake_path is
    the lake root -- a local path or an s3:// bucket. -#}
{%- set base = var("lake_path") -%}
{%- if var("lake_format", "parquet") == "ndjson" -%}
read_json_auto('{{ base }}/{{ source }}/{{ dataset }}/captured_date=*/*.ndjson.gz', hive_partitioning=true, union_by_name=true, ignore_errors=true)
{%- else -%}
read_parquet('{{ base }}/parquet/{{ source }}/{{ dataset }}/captured_date=*/*.parquet', hive_partitioning=true, union_by_name=true)
{%- endif -%}
{% endmacro %}
