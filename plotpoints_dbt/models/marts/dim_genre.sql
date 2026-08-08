-- One row per TMDB genre.

select
    g.value:id::number   as genre_id,
    max(g.value:name::string) as genre_name
from {{ ref('int_media') }} m,
     lateral flatten(input => m.record:tmdb:genres) g
where g.value:id is not null
group by genre_id
