-- One row per title (movie or TV), scalar attributes only. Grain: media_key.

select
    media_key,
    media_type,
    tmdb_id,
    title,
    original_title,
    release_date,
    runtime_minutes,
    original_language,
    overview,
    tagline,
    certification,
    imdb_id,
    tmdb_rating,
    vote_count,
    collection_id,
    collection_name,
    seasons,
    episodes
from {{ ref('int_media') }}
