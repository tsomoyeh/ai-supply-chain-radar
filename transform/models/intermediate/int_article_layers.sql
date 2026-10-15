-- 每則新聞屬於哪條鏈的哪一層，以及它的訊號分數
-- 只保留：LLM 判定相關、且不是「財報／營收公布」（避免資料洩漏）的新聞
-- 一則新聞可能透過公司或主題對應到同一層好幾次，用 distinct 避免重複計算
with eligible as (
    select *
    from {{ ref('stg_news_signals') }}
    where is_relevant
      and event_type != 'financial_report'
),

via_company as (
    select e.article_id, m.chain, m.layer
    from eligible as e
    join {{ ref('stg_article_companies') }} as ac using (article_id)
    join {{ ref('stg_chain_membership') }} as m using (stock_id)
),

via_topic as (
    select article_id, topic_chain as chain, topic_layer as layer
    from eligible
    where topic_layer is not null
),

article_layer as (
    select distinct * from via_company
    union
    select distinct * from via_topic
)

select
    al.chain,
    al.layer,
    e.article_id,
    e.month,
    e.event_type,
    e.direction,
    e.strength,
    e.direction * e.strength as signal_score  -- 正面重大事件 +3，負面重大事件 -3
from article_layer as al
join eligible as e using (article_id)
