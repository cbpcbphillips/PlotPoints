-- One row per title (movie or TV), scalar attributes only. Grain: media_key.
--
-- `franchise` is a first cut at "what series is this part of", in this order:
--   1. the explicit merges in seeds/franchise_merge.csv (Spider-Man spans four TMDB collections, the
--      MCU at least eight);
--   2. a shared-universe keyword in seeds/franchise_keywords.csv. TMDB gives Shang-Chi, Thunderbolts*,
--      Eternals, Black Widow, Justice League and others no collection at all, but its keywords do
--      carry "marvel cinematic universe (mcu)" / "dc extended universe (dceu)";
--   3. the TMDB collection's own name, else null for a standalone film.
-- Only ~21% of the catalog belongs to a collection, so null is the common case.

with universe as (
    select
        b.media_key,
        min(fk.franchise) as franchise
    from {{ ref('bridge_media_keyword') }} b
    join {{ ref('dim_keyword') }} k on k.keyword_id = b.keyword_id
    join {{ ref('franchise_keywords') }} fk on fk.keyword_name = k.keyword_name
    group by b.media_key
)

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
        u.franchise,
        nullif(trim(regexp_replace(m.collection_name, ' +Collection$', '', 1, 1, 'i')), '')
    ) as franchise,
    m.poster_path,
    m.backdrop_path,
    m.seasons,
    m.episodes
from {{ ref('int_media') }} m
left join {{ ref('franchise_merge') }} f on f.collection_id = m.collection_id
left join universe u on u.media_key = m.media_key
