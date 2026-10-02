-- One row per parcel per assessment roll year (3 years carried in taxlots).
with t as (select * from {{ ref('stg_taxlots') }} where nullif(PROPERTYID,'') is not null)
select PROPERTYID as property_id, try_cast(MKTVALYR1 as int) as roll_year, try_cast(TOTALVAL1 as double) as total_value from t
union all
select PROPERTYID, try_cast(MKTVALYR2 as int), try_cast(TOTALVAL2 as double) from t
union all
select PROPERTYID, try_cast(MKTVALYR3 as int), try_cast(TOTALVAL3 as double) from t
