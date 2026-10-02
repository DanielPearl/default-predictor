-- One row per residential demolition permit, keyed to its parcel by state_id
-- (STATEIDKEY matches taxlot STATE_ID; PROPERTYKEY is an internal numeric id).
select
  STATEIDKEY                                   as state_id,
  cast(PROPERTYKEY as varchar)                 as property_key,
  APPLICATION                                  as application,
  STATUS                                       as status,
  try_cast(nullif(cast("YEAR" as varchar), '') as integer) as demo_year,
  trim(concat_ws(' ', cast(HOUSE as varchar), DIRECTION, PROPSTREET, STREETTYPE)) as address
from {{ ref('stg_demolitions') }}
where nullif(STATEIDKEY, '') is not null
