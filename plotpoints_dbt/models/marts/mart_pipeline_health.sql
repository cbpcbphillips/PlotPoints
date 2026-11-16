-- Per-load-batch health of the RAW landings: did the enrichment match, and is the
-- metadata we embed from actually present?
--
-- This reads RAW directly (not the deduped staging views) on purpose. Staging collapses
-- repeated loads to the latest row, which is exactly what hides a bad batch: a run that
-- landed 5,000 half-empty titles looks fine once newer rows shadow it. Here each batch
-- stands alone, so degradation is attributable to the run that caused it.
--
-- Batch = the S3 run folder, e.g. 'catalog/20260926T225653Z' (source_file is
-- 'catalog/<run_id>/0000.jsonl').

with tagged as (

    select
        'tmdb_titles' as source,
        split_part(source_file, '/', 1) || '/' || split_part(source_file, '/', 2) as batch,
        loaded_at,
        record
    from {{ source('raw', 'tmdb_titles') }}

    union all

    select
        'diary_entries' as source,
        split_part(source_file, '/', 1) || '/' || split_part(source_file, '/', 2) as batch,
        loaded_at,
        record
    from {{ source('raw', 'diary_entries') }}

)

select
    source,
    batch,
    max(loaded_at)                                                         as loaded_at,
    count(*)                                                               as row_count,
    count_if(record:matched::boolean)                                      as matched_rows,
    round(count_if(record:matched::boolean) / count(*), 4)                 as match_rate,

    -- completeness of the fields the embedding document is built from
    round(count_if(nullif(trim(record:overview::string), '') is null) / count(*), 4)
                                                                           as pct_missing_overview,
    round(count_if(try_to_date(record:release_date::string) is null) / count(*), 4)
                                                                           as pct_missing_release_date,
    round(count_if(coalesce(array_size(record:genres), 0) = 0) / count(*), 4)
                                                                           as pct_missing_genres,
    round(count_if(coalesce(array_size(record:cast), 0) = 0) / count(*), 4)
                                                                           as pct_missing_cast
from tagged
group by source, batch
