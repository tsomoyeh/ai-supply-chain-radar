select chain, stock_id, layer, segment
from {{ source('raw', 'chain_membership') }}
