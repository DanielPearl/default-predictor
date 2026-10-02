-- Links a parcel to its (primary) owner, with occupancy.
select distinct
  PROPERTYID                                   as property_id,
  md5(upper(trim(OWNER1)))                     as owner_id,
  (upper(trim(OWNERADDR)) = upper(trim(SITEADDR)) and trim(OWNERADDR) <> '')
                                               as owner_occupied
from {{ ref('stg_taxlots') }}
where nullif(PROPERTYID, '') is not null and nullif(OWNER1, '') is not null
