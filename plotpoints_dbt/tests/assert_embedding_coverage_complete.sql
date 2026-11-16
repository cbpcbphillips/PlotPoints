{{ config(severity='warn') }}

-- Returns a row (= warns) when any title lacks a current embedding. Warn, not error: a
-- partial gap shouldn't fail the whole transform DAG, but it must be visible.
select *
from {{ ref('mart_embedding_coverage') }}
where missing_embedding > 0 or stale_embedding > 0
