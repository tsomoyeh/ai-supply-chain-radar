-- 月營收：統一欄位名稱、把 period 轉成日期，單位維持新台幣千元
select
    stock_id,
    company_name,
    market,
    cast(strptime(period || '-01', '%Y-%m-%d') as date) as month,
    revenue as revenue_k_twd,
    revenue_last_year as revenue_last_year_k_twd,
    yoy_pct
from {{ source('raw', 'mops_revenue') }}
where revenue is not null
