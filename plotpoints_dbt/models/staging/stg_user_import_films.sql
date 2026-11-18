-- Films from consented imports (the S3 inbox), one row per (user, title): the latest import wins.
--
-- A deletion request removes an import everywhere. The physical DELETE in user_ingest.py is the
-- real removal; filtering on the tombstones here is the belt to that braces, so even if a deleted
-- import's file were ever landed again it could not reach the marts.

with imports as (
    select *
    from {{ source('raw', 'user_imports') }}
    where token_hash not in (select token_hash from {{ source('raw', 'user_deletions') }})
    qualify row_number() over (partition by import_id order by loaded_at desc) = 1
),

films as (
    select
        i.import_id,
        i.record:user_id::string               as user_id,
        i.record:source::string                as import_source,
        try_to_timestamp_tz(i.record:consented_at::string) as consented_at,
        f.value:media_type::string              as media_type,
        f.value:tmdb_id::number                 as tmdb_id,
        f.value:rating::float                   as rating,
        coalesce(f.value:rewatch::boolean, false) as rewatch
    from imports i, lateral flatten(input => i.record:films) f
    where f.value:tmdb_id is not null
)

select *
from films
qualify row_number() over (
    partition by user_id, media_type, tmdb_id order by consented_at desc nulls last, import_id
) = 1
