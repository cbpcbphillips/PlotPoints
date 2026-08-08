-- Fact grain: one Letterboxd watch event. Measures: rating, rewatch. FKs to
-- dim_media (media_key), dim_user (user_id), dim_date (watched_date).

select
    md5(letterboxd_username || '|' || guid)  as diary_entry_key,
    letterboxd_username                       as user_id,
    {{ media_key('media_type', 'tmdb_id') }}  as media_key,
    media_type,
    tmdb_id,
    watched_date,
    rating,
    rewatch,
    matched
from {{ ref('stg_diary_entries') }}
