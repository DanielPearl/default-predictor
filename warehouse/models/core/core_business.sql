-- Oregon SoS registry pivoted to one row per business (addresses by role).
-- Presence here = active entity; absence for an entity owner = dissolved.
select
  registry_number,
  any_value(business_name)                     as business_name,
  any_value(entity_type)                       as entity_type,
  any_value(registry_date)                     as registry_date,
  max(case when associated_name_type = 'PRINCIPAL PLACE OF BUSINESS' then address end) as principal_address,
  max(case when associated_name_type = 'PRINCIPAL PLACE OF BUSINESS' then city    end) as principal_city,
  max(case when associated_name_type = 'REGISTERED AGENT'            then address end) as agent_address,
  max(case when associated_name_type = 'REGISTERED AGENT'            then city    end) as agent_city
from {{ ref('stg_sos_businesses') }}
where registry_number is not null
group by registry_number
