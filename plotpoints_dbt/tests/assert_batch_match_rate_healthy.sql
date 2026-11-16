{{ config(severity='warn') }}

-- Returns a row (= warns) for any load batch where under 95% of records matched a TMDB
-- title. A low rate means the enrichment degraded (bad API key, TMDB outage, wrong ids)
-- even though the load itself "succeeded" -- the silent failure this model exists to catch.
select *
from {{ ref('mart_pipeline_health') }}
where match_rate < 0.95
