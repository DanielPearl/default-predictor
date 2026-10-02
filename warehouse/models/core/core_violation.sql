-- One row per code-enforcement case, classified by type.
with v as (
  select *,
    lower(coalesce(type,'') || ' ' || coalesce(work,'') || ' ' || coalesce(description,'')) as txt
  from {{ ref('stg_violations') }}
  where property_id is not null
)
select
  property_id,
  coalesce(application_number, ivr_number)     as case_id,
  type, work, status,
  case
    when txt like '%vacant%' or txt like '%derelict%' or txt like '%dangerous%' or txt like '%boarded%' then 'vacant'
    when txt like '%trash%'  or txt like '%debris%'   or txt like '%garbage%'   or txt like '%junk%'    then 'trash'
    when txt like '%overgrown%' or txt like '%tall grass%' or txt like '%weed%' or txt like '%vegetation%' then 'overgrowth'
    when txt like '%vehicle%' or txt like '%trailer%' or txt like '%boat%'      then 'vehicle'
    when txt like '%zoning%'  then 'zoning'
    when txt like '%noise%'   then 'noise'
    else 'other'
  end                                          as violation_type
from v
