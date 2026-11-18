-- One row per person with a history: a Letterboxd RSS diary, a consented import, or both.

select user_id, user_id as username
from (
    select letterboxd_username as user_id from {{ ref('stg_diary_entries') }}
    union
    select user_id from {{ ref('stg_user_import_films') }}
)
