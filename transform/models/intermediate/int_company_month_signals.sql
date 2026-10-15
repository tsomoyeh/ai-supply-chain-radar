-- 每家公司每個月的新聞訊號彙總（給儀表板的公司頁面使用）
select
    ac.stock_id,
    s.month,
    count(*) as n_articles,
    count(*) filter (where s.direction > 0) as n_positive,
    count(*) filter (where s.direction < 0) as n_negative,
    sum(s.direction * s.strength) as net_score,
    avg(s.direction * s.strength) as avg_score
from {{ ref('stg_news_signals') }} as s
join {{ ref('stg_article_companies') }} as ac using (article_id)
where s.is_relevant
  and s.event_type != 'financial_report'
group by ac.stock_id, s.month
