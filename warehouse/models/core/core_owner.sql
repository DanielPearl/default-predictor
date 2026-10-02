-- Owner entity (primary owner per parcel, deduped by normalized name).
-- NOTE: multi-owner "A & B" splitting is a later entity-resolution refinement.
with o as (
  select
    upper(trim(OWNER1))                       as owner_name,
    upper(trim(OWNERADDR))                     as owner_mailing_address,
    upper(trim(OWNERCITY))                     as owner_city,
    upper(trim(OWNERSTATE))                    as owner_state,
    left(OWNERZIP, 5)                          as owner_zip
  from {{ ref('stg_taxlots') }}
  where nullif(OWNER1, '') is not null
)
select
  md5(owner_name)                              as owner_id,
  owner_name,
  any_value(owner_mailing_address)             as owner_mailing_address,
  any_value(owner_city)                        as owner_city,
  any_value(owner_state)                       as owner_state,
  any_value(owner_zip)                         as owner_zip,
  regexp_matches(owner_name,
    '(\bLLC\b|\bINC\b|\bCORP\b|\bTRUST\b|\bLP\b|\bLTD\b|\bCOMPANY\b|\bPARTNERS\b|\bPROPERTIES\b|\bHOLDINGS\b|\bINVESTMENTS\b|\bBANK\b|\bASSOCIATION\b|\bCHURCH\b|\bHOMES\b|CITY OF|STATE OF|COUNTY OF)')
                                               as is_entity,
  (any_value(owner_state) is not null and any_value(owner_state) <> 'OR') as out_of_state
from o
group by owner_name
