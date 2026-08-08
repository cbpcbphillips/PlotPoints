-- Every title we know about: the catalog plus any title a user actually watched
-- (diary entries carry the same enriched `record`). One row per (media_type, tmdb_id);
-- catalog wins over diary on conflict. Keeps `record` for downstream flattening.

with catalog as (
    select media_type, tmdb_id, record, loaded_at, 1 as source_rank
    from {{ ref('stg_tmdb_titles') }}
),

diary as (
    select media_type, tmdb_id, record, loaded_at, 2 as source_rank
    from {{ ref('stg_diary_entries') }}
    where tmdb_id is not null and media_type is not null
),

unioned as (
    select * from catalog
    union all
    select * from diary
)

select
    {{ media_key('media_type', 'tmdb_id') }} as media_key,
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
    record:seasons::number                   as seasons,
    record:episodes::number                  as episodes,
    record
from unioned
qualify row_number() over (partition by media_type, tmdb_id order by source_rank, loaded_at desc) = 1
