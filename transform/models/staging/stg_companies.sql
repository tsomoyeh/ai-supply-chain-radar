-- 追蹤的公司清單
select
    stock_id,
    name_zh,
    name_en,
    country
from {{ source('raw', 'companies') }}
