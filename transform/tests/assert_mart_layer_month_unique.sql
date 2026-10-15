-- 總表每條鏈、每一層、每個月只能有一筆
select chain, layer, month, count(*) as n
from {{ ref('mart_layer_month') }}
group by chain, layer, month
having count(*) > 1
