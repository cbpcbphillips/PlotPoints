-- The vectorized catalog: one embedding per title, the corpus Phase 5's taste
-- vector gets compared against.
--
-- This is the only model that spends Cortex credits, so it is incremental by
-- design rather than as a later optimisation. On a rerun it embeds only what
-- actually changed:
--   * new titles            -- no matching media_key
--   * edited titles         -- document_hash moved
--   * a model switch        -- embedding_model is part of the match
-- Everything else costs nothing.
--
-- NOTE: `dbt build --full-refresh` re-embeds the entire catalog. Free at 60 rows,
-- a real bill at the 50k target against the 25-credit resource monitor.

{{
    config(
        materialized='incremental',
        unique_key='media_key',
        incremental_strategy='merge'
    )
}}

with documents as (

    select * from {{ ref('int_media_document') }}

),

to_embed as (

    select *
    from documents d

    {% if is_incremental() %}
    where not exists (
        select 1
        from {{ this }} e
        where e.media_key       = d.media_key
          and e.document_hash   = d.document_hash
          and e.embedding_model = '{{ var("embedding_model") }}'
    )
    {% endif %}

)

select
    media_key,
    media_type,
    tmdb_id,
    document_hash,
    '{{ var("embedding_model") }}' as embedding_model,
    {{ embed_text('document') }}   as embedding,
    current_timestamp()            as embedded_at
from to_embed
