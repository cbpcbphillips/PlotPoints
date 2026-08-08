-- Letterboxd watch events: dedupe on the natural key (latest load wins), type the VARIANT.

with deduped as (
    select *
    from {{ source('raw', 'diary_entries') }}
    qualify row_number() over (partition by letterboxd_username, guid order by loaded_at desc) = 1
)

select
    letterboxd_username,
    guid,
    media_type,
    record:tmdb_id::number                    as tmdb_id,
    record:rating::float                      as rating,
    record:rewatch::boolean                   as rewatch,
    try_to_date(record:watched_date::string)  as watched_date,
    record:film_title::string                 as film_title,
    record:film_year::number                  as film_year,
    record:matched::boolean                   as matched,
    record,
    loaded_at
from deduped
