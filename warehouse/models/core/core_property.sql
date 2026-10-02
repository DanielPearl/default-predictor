-- Parcel hub: one row per property (latest capture), physical + value attrs.
select
  PROPERTYID                          as property_id,
  STATE_ID                            as state_id,
  trim(SITEADDR)                      as site_address,
  left(SITEZIP, 5)                    as site_zip,
  PRPCD_DESC                          as property_class,
  LANDUSE                             as land_use,
  TAXCODE                             as tax_code,
  COUNTY                              as county,
  try_cast(YEARBUILT as integer)      as year_built,
  try_cast(BLDGSQFT  as double)       as building_sqft,
  try_cast(BEDROOMS  as double)       as bedrooms,
  try_cast(UNITS     as double)       as units,
  try_cast(A_T_SQFT  as double)       as lot_sqft,
  try_cast(LANDVAL1  as double)       as land_value,
  try_cast(BLDGVAL1  as double)       as building_value,
  try_cast(TOTALVAL3 as double)       as assessed_value,
  try_cast(TOTALVAL1 as double)       as assessed_value_prior,
  try_cast(SALEPRICE as double)       as last_sale_price,
  nullif(SALEDATE, '')                as last_sale_date,
  captured_date
from {{ ref('stg_taxlots') }}
where nullif(PROPERTYID, '') is not null
qualify row_number() over (partition by PROPERTYID order by captured_date desc) = 1
