select distinct article_id, stock_id
from {{ source('raw', 'article_companies') }}
