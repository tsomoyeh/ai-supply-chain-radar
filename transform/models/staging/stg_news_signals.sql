-- 每則新聞的 LLM 判斷，加上發布月份與主題查詢的鏈、層級
select
    s.article_id,
    s.title,
    s.source,
    s.lang,
    s.published_at,
    cast(date_trunc('month', s.published_at) as date) as month,
    s.relevant = 1 as is_relevant,
    s.event_type,
    cast(s.direction as integer) as direction,
    cast(s.strength as integer) as strength,
    coalesce(s.provider, 'groq') as provider,  -- 最早 2,400 則是直接用 Groq 跑的，沒有記錄服務商
    a.topic_chain,
    a.topic_layer
from {{ source('raw', 'llm_signals') }} as s
left join {{ source('raw', 'news_articles') }} as a using (article_id)
