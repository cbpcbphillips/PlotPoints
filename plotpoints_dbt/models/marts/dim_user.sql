-- One row per Letterboxd user seen in the diary.

select distinct
    letterboxd_username as user_id,
    letterboxd_username as username
from {{ ref('stg_diary_entries') }}
