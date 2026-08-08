-- Media <-> genre, many-to-many.

select distinct
    m.media_key,
    m.media_type,
    m.tmdb_id,
    g.value:id::number as genre_id
from {{ ref('int_media') }} m,
     lateral flatten(input => m.record:tmdb:genres) g
where g.value:id is not null
