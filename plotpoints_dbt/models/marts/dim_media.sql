-- One row per title (movie or TV), scalar attributes only. Grain: media_key.
--
-- `franchise` is a first cut at "what series is this part of": the explicit merges in
-- seeds/franchise_merge.csv (Spider-Man spans four TMDB collections, the MCU at least eight), else the
-- TMDB collection's own name, else null for a standalone film. Only ~21% of the catalog belongs to a
-- collection at all, so null is the common case.

select
    m.media_key,
    m.media_type,
    m.tmdb_id,
    m.title,
    m.original_title,
    m.release_date,
    m.runtime_minutes,
    m.original_language,
    m.overview,
    m.tagline,
    m.certification,
    m.imdb_id,
    m.tmdb_rating,
    m.vote_count,
    m.collection_id,
    m.collection_name,
    coalesce(
        f.franchise,
        nullif(trim(regexp_replace(m.collection_name, ' +Collection$', '', 1, 1, 'i')), '')
    ) as franchise,
    m.poster_path,
    m.backdrop_path,
    m.seasons,
    m.episodes
from {{ ref('int_media') }} m
left join {{ ref('franchise_merge') }} f on f.collection_id = m.collection_id
