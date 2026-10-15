-- 每條鏈、每一層、每個月只能有一筆彙總
select chain, layer, month, count(*) as n
from {{ ref('int_layer_month_signals') }}
group by chain, layer, month
having count(*) > 1
