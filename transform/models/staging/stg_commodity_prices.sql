-- 原物料價格：加上中文名稱和對應的鏈、層級
select
    p.series_id,
    c.name_zh,
    c.chain,
    c.layer,
    c.related_segments,
    cast(strptime(p.period || '-01', '%Y-%m-%d') as date) as month,
    p.value,
    p.yoy_pct
from {{ source('raw', 'commodity_prices') }} as p
left join {{ source('raw', 'commodities') }} as c using (series_id)
