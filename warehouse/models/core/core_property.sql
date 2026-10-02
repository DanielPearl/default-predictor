-- One row per parcel: taxlot base features + the violations distress rollup.
select
  t.PROPERTYID                        as property_id,
  t.SITEADDR                          as site_address,
  t.OWNER1                            as owner,
  nullif(t.OWNERCITY, '')             as owner_city,
  nullif(t.OWNERSTATE, '')            as owner_state,
  try_cast(t.YEARBUILT as integer)    as year_built,
  try_cast(t.TOTALVAL3 as double)     as assessed_value,
  try_cast(t.TOTALVAL1 as double)     as assessed_value_prior,
  case when upper(trim(t.OWNERADDR)) = upper(trim(t.SITEADDR))
       then 'Owner-occupied' else 'Absentee' end as occupancy,
  coalesce(v.violation_count, 0)      as violation_count,
  coalesce(v.violation_vacant, 0)     as violation_vacant,
  coalesce(v.violation_trash, 0)      as violation_trash,
  coalesce(v.violation_overgrowth, 0) as violation_overgrowth
from {{ ref('stg_taxlots') }} t
left join {{ ref('core_violations_by_property') }} v on v.property_id = t.PROPERTYID
where nullif(t.PROPERTYID, '') is not null
