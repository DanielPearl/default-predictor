-- One row per building permit, keyed to its parcel.
select
  PROPLOT                                      as property_id,
  FOLDERNUMB                                   as permit_id,
  NEWCLASS                                     as permit_class,
  NEWTYPE                                      as permit_type,
  WORKDESC                                     as work,
  STATUS                                       as status,
  try_cast(YEAR_ as integer)                   as permit_year,
  try_cast(VALUATION as double)                as valuation,
  (upper(coalesce(IS_ADU,'')) = 'TRUE')        as is_adu,
  case when try_cast(ISSUEDATE as bigint) > 0
       then to_timestamp(try_cast(ISSUEDATE as bigint)/1000)::date end as issue_date
from {{ ref('stg_permits') }}
where nullif(PROPLOT, '') is not null
