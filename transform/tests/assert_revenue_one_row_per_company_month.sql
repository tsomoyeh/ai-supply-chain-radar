-- 每家公司每個月只能有一筆營收；有回傳任何列就代表測試失敗
select stock_id, month, count(*) as n
from {{ ref('stg_revenue') }}
group by stock_id, month
having count(*) > 1
