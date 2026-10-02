-- One row per parcel per snapshot (week): the model's feature/training table.
with viol as (
  select property_id,
         count(*)                                         as violation_count,
         count(*) filter (where violation_type='vacant')  as violation_vacant,
         count(*) filter (where violation_type='trash')   as violation_trash,
         count(*) filter (where violation_type='overgrowth') as violation_overgrowth
  from {{ ref('core_violation') }} group by property_id
),
perm as (
  select property_id, count(*) as permit_count, max(permit_year) as last_permit_year
  from {{ ref('core_permit') }} group by property_id
),
demo as (
  select state_id, count(*) as demolition_count
  from {{ ref('core_demolition') }} group by state_id
)
select
  p.property_id,
  p.captured_date                                         as snapshot_date,
  p.site_address, p.land_use, p.property_class,
  p.year_built, p.building_sqft, p.lot_sqft,
  p.assessed_value, p.assessed_value_prior,
  round((p.assessed_value - p.assessed_value_prior)
        / nullif(p.assessed_value_prior, 0) * 100, 1)      as value_trend_pct,
  p.last_sale_date, p.last_sale_price,
  o.owner_name, o.owner_city, o.owner_state,
  o.is_entity, o.out_of_state,
  ow.owner_occupied,
  case when ow.owner_occupied then 'Owner-occupied' else 'Absentee' end as occupancy,
  coalesce(viol.violation_count, 0)      as violation_count,
  coalesce(viol.violation_vacant, 0)     as violation_vacant,
  coalesce(viol.violation_trash, 0)      as violation_trash,
  coalesce(viol.violation_overgrowth, 0) as violation_overgrowth,
  coalesce(perm.permit_count, 0)         as permit_count,
  perm.last_permit_year,
  coalesce(demo.demolition_count, 0)     as demolition_count
from {{ ref('core_property') }} p
left join {{ ref('core_ownership') }} ow on ow.property_id = p.property_id
left join {{ ref('core_owner') }} o       on o.owner_id   = ow.owner_id
left join viol on viol.property_id = p.property_id
left join perm on perm.property_id = p.property_id
left join demo on demo.state_id = p.state_id
