-- 每家公司每月：新聞訊號 + 營收年增率，給儀表板的層級深入頁使用
with spine as (
    select stock_id, month from {{ ref('int_company_month_signals') }}
    union
    select stock_id, month from {{ ref('stg_revenue') }}
    where stock_id in (select stock_id from {{ ref('stg_companies') }})
)

select
    sp.stock_id,
    c.name_zh,
    c.name_en,
    m.chain,
    m.layer,
    m.segment,
    sp.month,
    s.n_articles,
    s.n_positive,
    s.n_negative,
    s.avg_score,
    r.revenue_k_twd,
    r.yoy_pct as revenue_yoy_pct
from spine as sp
join {{ ref('stg_companies') }} as c using (stock_id)
left join {{ ref('stg_chain_membership') }} as m using (stock_id)
left join {{ ref('int_company_month_signals') }} as s using (stock_id, month)
left join {{ ref('stg_revenue') }} as r using (stock_id, month)
