{{ config(severity='warn') }}
-- 資料完整性：追蹤的台灣公司，在已過公布期限（次月 15 日）的月份都應該有營收
-- 缺資料只發出警告、不讓管線失敗；MOPS 的彙總頁不會補上晚公布的公司
with months as (
    select distinct month
    from {{ ref('stg_revenue') }}
    where month >= date '2024-01-01'
      and month + interval 1 month + interval 14 day < current_date
),

expected as (
    select c.stock_id, c.name_zh, m.month
    from {{ ref('stg_companies') }} as c
    cross join months as m
    where c.country = 'TW'
)

select e.stock_id, e.name_zh, e.month
from expected as e
left join {{ ref('stg_revenue') }} as r using (stock_id, month)
where r.stock_id is null
