-- Lightweight date dimension: the distinct dates that appear as watch dates or
-- release dates. (A contiguous spine can replace this later if time analysis needs it.)

with dates as (
    select watched_date as date_day
    from {{ ref('stg_diary_entries') }}
    where watched_date is not null
    union
    select release_date as date_day
    from {{ ref('int_media') }}
    where release_date is not null
)

select
    date_day,
    year(date_day)      as year,
    month(date_day)     as month,
    day(date_day)       as day_of_month,
    dayofweek(date_day) as day_of_week
from dates
