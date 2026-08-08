-- Catalog titles: dedupe on the natural key (latest load wins), type the VARIANT.
-- The full `record` is kept so marts can flatten credits/genres/keywords from record:tmdb.

with deduped as (
    select *
    from {{ source('raw', 'tmdb_titles') }}
    qualify row_number() over (partition by media_type, tmdb_id order by loaded_at desc) = 1
)

select
    media_type,
    tmdb_id,
    record:title::string                     as title,
    record:original_title::string            as original_title,
    try_to_date(record:release_date::string) as release_date,
    record:runtime::number                   as runtime_minutes,
    record:original_language::string         as original_language,
    record:overview::string                  as overview,
    record:tagline::string                   as tagline,
    record:certification::string             as certification,
    record:imdb_id::string                   as imdb_id,
    record:tmdb_rating::float                as tmdb_rating,
    record:vote_count::number                as vote_count,
    record:collection_id::number             as collection_id,
    record:collection_name::string           as collection_name,
    record                                   as record,
    loaded_at
from deduped
