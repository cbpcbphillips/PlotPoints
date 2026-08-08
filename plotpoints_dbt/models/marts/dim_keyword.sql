-- One row per TMDB keyword (theme/tag). coalesce handles movie (`keywords`) vs TV (`results`).

select
    k.value:id::number   as keyword_id,
    max(k.value:name::string) as keyword_name
from {{ ref('int_media') }} m,
     lateral flatten(
         input => coalesce(m.record:tmdb:keywords:keywords, m.record:tmdb:keywords:results)
     ) k
where k.value:id is not null
group by keyword_id
