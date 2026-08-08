-- Flatten each title's people into (media, person, role) rows. We keep only the
-- top-billed cast and the key crew roles — the raw blob keeps the full 500-person
-- crew if ever needed, but that would bloat the bridge by ~20x.
--
-- coalesce() handles both shapes: movies use `credits` (crew has a single `job`),
-- TV uses `aggregate_credits` (cast roles[] / crew jobs[] arrays).

with media as (
    select media_key, media_type, tmdb_id, record
    from {{ ref('int_media') }}
),

cast_members as (
    select
        m.media_key,
        m.media_type,
        m.tmdb_id,
        c.value:id::number                                                   as person_id,
        c.value:name::string                                                 as person_name,
        'cast'                                                               as role,
        coalesce(c.value:character::string, c.value:roles[0]:character::string) as character,
        c.value:order::number                                               as cast_order
    from media m,
         lateral flatten(
             input => coalesce(m.record:tmdb:credits:cast, m.record:tmdb:aggregate_credits:cast)
         ) c
    where c.value:order::number < 15
),

crew_members as (
    select
        m.media_key,
        m.media_type,
        m.tmdb_id,
        c.value:id::number                                        as person_id,
        c.value:name::string                                      as person_name,
        coalesce(c.value:job::string, c.value:jobs[0]:job::string) as role,
        null                                                      as character,
        null                                                      as cast_order
    from media m,
         lateral flatten(
             input => coalesce(m.record:tmdb:credits:crew, m.record:tmdb:aggregate_credits:crew)
         ) c
    where coalesce(c.value:job::string, c.value:jobs[0]:job::string) in (
        'Director', 'Writer', 'Screenplay', 'Story', 'Producer', 'Executive Producer',
        'Director of Photography', 'Original Music Composer', 'Editor'
    )
)

select * from cast_members
union all
select * from crew_members
