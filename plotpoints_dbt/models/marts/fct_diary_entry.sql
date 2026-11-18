-- Fact grain: one watch event. Measures: rating, rewatch. FKs to dim_media (media_key),
-- dim_user (user_id), dim_date (watched_date).
--
-- Two sources feed it. `letterboxd_rss` rows are real watch events with dates. `import` rows come
-- from a consented export or username import via the S3 inbox: they say a film was seen and how it
-- was rated, but carry no date. The recommender counts a film as a rewatch only from the RSS rows
-- (or an import's own Rewatch flag), so a film present in both sources is not double-counted.
--
-- Import rows wait for their title: one the catalog has not enriched yet joins in on the run after
-- user_ingest lands it, rather than breaking the dim_media relationship.

select
    md5(letterboxd_username || '|' || guid)  as diary_entry_key,
    letterboxd_username                       as user_id,
    {{ media_key('media_type', 'tmdb_id') }}  as media_key,
    media_type,
    tmdb_id,
    watched_date,
    rating,
    rewatch,
    matched,
    'letterboxd_rss'                          as source
from {{ ref('stg_diary_entries') }}

union all

select
    md5(f.user_id || '|import|' || f.media_type || '|' || f.tmdb_id::string) as diary_entry_key,
    f.user_id,
    m.media_key,
    f.media_type,
    f.tmdb_id,
    null::date                                as watched_date,
    f.rating,
    f.rewatch,
    true                                      as matched,
    'import'                                  as source
from {{ ref('stg_user_import_films') }} f
inner join {{ ref('int_media') }} m
    on m.media_type = f.media_type and m.tmdb_id = f.tmdb_id
