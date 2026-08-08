-- Media <-> keyword, many-to-many.

select distinct
    m.media_key,
    m.media_type,
    m.tmdb_id,
    k.value:id::number as keyword_id
from {{ ref('int_media') }} m,
     lateral flatten(
         input => coalesce(m.record:tmdb:keywords:keywords, m.record:tmdb:keywords:results)
     ) k
where k.value:id is not null
