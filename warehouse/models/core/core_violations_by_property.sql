-- Roll up code cases to one row per property, classified by type.
with v as (
  select property_id,
         lower(coalesce(type,'') || ' ' || coalesce(work,'') || ' ' || coalesce(description,'')) as txt
  from {{ ref('stg_violations') }}
  where property_id is not null
)
select
  property_id,
  count(*) as violation_count,
  count(*) filter (where txt like '%vacant%' or txt like '%derelict%'
                      or txt like '%dangerous%' or txt like '%boarded%') as violation_vacant,
  count(*) filter (where txt like '%trash%' or txt like '%debris%'
                      or txt like '%garbage%' or txt like '%junk%')      as violation_trash,
  count(*) filter (where txt like '%overgrown%' or txt like '%tall grass%'
                      or txt like '%weed%' or txt like '%vegetation%')   as violation_overgrowth
from v
group by property_id
