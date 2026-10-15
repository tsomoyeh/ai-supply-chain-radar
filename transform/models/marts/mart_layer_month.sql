-- 每條鏈、每一層、每個月的總表：新聞訊號指數 + 營收年增率 + 原物料價格年增率
-- 這是儀表板與領先落後分析直接使用的表

with signals as (
    select
        chain,
        layer,
        month,
        n_articles,
        n_positive,
        n_negative,
        avg_score,
        -- 3 個月移動平均，降低新聞少的月份造成的雜訊
        avg(avg_score) over (
            partition by chain, layer order by month
            rows between 2 preceding and current row
        ) as score_3m
    from {{ ref('int_layer_month_signals') }}
),

signals_with_baseline as (
    select
        *,
        -- 基準只用「過去」的月份，避免前視偏誤（不能用未來的資料標準化現在的數字）
        avg(score_3m) over past as baseline_mean,
        stddev_samp(score_3m) over past as baseline_std,
        count(*) over past as baseline_months
    from signals
    window past as (
        partition by chain, layer order by month
        rows between unbounded preceding and 1 preceding
    )
),

signal_index as (
    select
        *,
        -- 高於或低於這一層過去平均多少個標準差；至少累積 6 個月才計算
        case
            when baseline_months >= 6 and baseline_std > 0
                then (score_3m - baseline_mean) / baseline_std
        end as signal_index
    from signals_with_baseline
),

layer_revenue as (
    -- 同一層的營收先加總再算年增率，大公司的權重比較合理
    select
        m.chain,
        m.layer,
        r.month,
        (sum(r.revenue_k_twd) / nullif(sum(r.revenue_last_year_k_twd), 0) - 1) * 100 as revenue_yoy_pct,
        count(*) as n_companies_reported
    from {{ ref('stg_revenue') }} as r
    join {{ ref('stg_chain_membership') }} as m using (stock_id)
    group by m.chain, m.layer, r.month
),

layer_commodities as (
    select
        chain,
        layer,
        month,
        avg(yoy_pct) as commodity_yoy_pct,
        string_agg(name_zh, '、' order by name_zh) as commodities
    from {{ ref('stg_commodity_prices') }}
    group by chain, layer, month
),

spine as (
    select chain, layer, month from signal_index
    union
    select chain, layer, month from layer_revenue
    union
    select chain, layer, month from layer_commodities
)

select
    sp.chain,
    sp.layer,
    sp.month,
    sp.month < date_trunc('month', current_date) as is_complete_month,
    s.n_articles,
    s.n_positive,
    s.n_negative,
    s.avg_score,
    s.score_3m,
    s.signal_index,
    r.revenue_yoy_pct,
    r.n_companies_reported,
    c.commodity_yoy_pct,
    c.commodities
from spine as sp
left join signal_index as s using (chain, layer, month)
left join layer_revenue as r using (chain, layer, month)
left join layer_commodities as c using (chain, layer, month)
