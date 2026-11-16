-- One row: is every title that should have an embedding actually embedded, and is each
-- embedding current for its document?
--
-- media_embeddings is incremental on document_hash, so there are two distinct ways it can
-- be wrong, and they need different fixes:
--   missing_embedding -- a document exists with no embedding at all (a failed or skipped run)
--   stale_embedding   -- an embedding exists but for an older document or a different model
--                        (the source data or the embedding_model var changed since)
-- Both heal on the next `dbt build`; a non-zero value after a build means something is wrong.

with documents as (

    select media_key, document_hash from {{ ref('int_media_document') }}

),

embeddings as (

    select media_key, document_hash, embedding_model from {{ ref('media_embeddings') }}

)

select
    (select count(*) from {{ ref('dim_media') }})                          as titles,
    count(d.media_key)                                                     as documents,
    count_if(
        e.media_key is not null
        and e.document_hash = d.document_hash
        and e.embedding_model = '{{ var("embedding_model") }}'
    )                                                                      as embedded_current,
    count_if(e.media_key is null)                                          as missing_embedding,
    count_if(
        e.media_key is not null
        and (e.document_hash != d.document_hash
             or e.embedding_model != '{{ var("embedding_model") }}')
    )                                                                      as stale_embedding,
    round(
        count_if(
            e.media_key is not null
            and e.document_hash = d.document_hash
            and e.embedding_model = '{{ var("embedding_model") }}'
        ) / nullif(count(d.media_key), 0),
        4
    )                                                                      as coverage,
    current_timestamp()                                                    as measured_at
from documents d
left join embeddings e on e.media_key = d.media_key
