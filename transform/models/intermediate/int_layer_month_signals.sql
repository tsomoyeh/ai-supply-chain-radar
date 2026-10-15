-- 每條鏈、每一層、每個月的新聞訊號彙總
select
    chain,
    layer,
    month,
    count(*) as n_articles,
    count(*) filter (where direction > 0) as n_positive,
    count(*) filter (where direction < 0) as n_negative,
    sum(signal_score) as net_score,
    avg(signal_score) as avg_score
from {{ ref('int_article_layers') }}
group by chain, layer, month
