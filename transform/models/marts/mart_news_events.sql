-- 每則相關新聞一列，附上涉及的公司與層級，給儀表板的事件列表使用
-- 保留財報類（監測時有參考價值），但在 is_reported_result 標記出來
with company_names as (
    select
        ac.article_id,
        string_agg(distinct c.name_zh, '、') as companies_zh,
        string_agg(distinct c.name_en, ', ') as companies_en
    from {{ ref('stg_article_companies') }} as ac
    join {{ ref('stg_companies') }} as c using (stock_id)
    group by ac.article_id
),

layers as (
    select article_id, string_agg(distinct layer, '|' order by layer) as layers
    from (
        select ac.article_id, m.layer
        from {{ ref('stg_article_companies') }} as ac
        join {{ ref('stg_chain_membership') }} as m using (stock_id)
        union
        select article_id, topic_layer as layer
        from {{ ref('stg_news_signals') }}
        where topic_layer is not null
    )
    group by article_id
)

select
    s.article_id,
    s.published_at,
    s.month,
    s.title,
    s.source,
    s.lang,
    s.link,
    s.event_type,
    s.direction,
    s.strength,
    s.event_type = 'financial_report' as is_reported_result,
    l.layers,
    cn.companies_zh,
    cn.companies_en
from {{ ref('stg_news_signals') }} as s
left join layers as l using (article_id)
left join company_names as cn using (article_id)
where s.is_relevant
