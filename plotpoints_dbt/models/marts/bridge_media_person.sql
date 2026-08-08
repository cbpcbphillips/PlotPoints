-- Media <-> person, many-to-many, one row per (title, person, role).
-- role is 'cast' or a crew job (Director, Writer, ...); character/cast_order for cast.

select distinct
    media_key,
    media_type,
    tmdb_id,
    person_id,
    role,
    character,
    cast_order
from {{ ref('int_media_people') }}
where person_id is not null
