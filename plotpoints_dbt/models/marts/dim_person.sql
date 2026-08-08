-- One row per person (deduped on TMDB person_id — names repeat across films, ids don't).

select
    person_id,
    max(person_name) as person_name
from {{ ref('int_media_people') }}
where person_id is not null
group by person_id
