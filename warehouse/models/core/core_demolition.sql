-- One row per residential demolition permit, keyed to its parcel.
select
  PROPERTYKEY                                  as property_id,
  STATEIDKEY                                   as state_id,
  APPLICATION                                  as application,
  STATUS                                       as status,
  try_cast(YEAR as integer)                    as demo_year,
  trim(concat_ws(' ', HOUSE, DIRECTION, PROPSTREET, STREETTYPE)) as address
from {{ ref('stg_demolitions') }}
where nullif(PROPERTYKEY, '') is not null
