-- The text we embed: one labeled document per title, built from the star schema
-- rather than by re-flattening `record`, so it always agrees with the dims/bridges
-- the marts are tested against.
--
-- Field set (roadmap "Decisions made" #4): theme *and* people -- genres, keywords,
-- overview and tagline carry subject matter; director and top cast carry the
-- affinity that drives a lot of real taste ("anything by Fincher").
--
-- document_hash is what makes re-embedding cheap: media_embeddings only calls
-- Cortex for titles whose hash moved. Keep the document deterministic -- the
-- listagg ORDER BYs are load-bearing, not cosmetic. Anything non-deterministic
-- here re-embeds the whole catalog on every run.

with genres as (
    select
        b.media_key,
        listagg(g.genre_name, ', ') within group (order by g.genre_name) as genre_list
    from {{ ref('bridge_media_genre') }} b
    join {{ ref('dim_genre') }} g on g.genre_id = b.genre_id
    group by b.media_key
),

keywords as (
    select
        b.media_key,
        listagg(k.keyword_name, ', ') within group (order by k.keyword_name) as keyword_list
    from {{ ref('bridge_media_keyword') }} b
    join {{ ref('dim_keyword') }} k on k.keyword_id = b.keyword_id
    group by b.media_key
),

directors as (
    select
        b.media_key,
        listagg(p.person_name, ', ') within group (order by p.person_name) as director_list
    from {{ ref('bridge_media_person') }} b
    join {{ ref('dim_person') }} p on p.person_id = b.person_id
    where b.role = 'Director'
    group by b.media_key
),

-- billing order, not alphabetical: the leads should lead
top_cast as (
    select
        b.media_key,
        listagg(p.person_name, ', ') within group (order by b.cast_order) as cast_list
    from {{ ref('bridge_media_person') }} b
    join {{ ref('dim_person') }} p on p.person_id = b.person_id
    where b.role = 'cast'
      and b.cast_order < 10
    group by b.media_key
),

assembled as (
    select
        m.media_key,
        m.media_type,
        m.tmdb_id,
        m.title,
        -- array_construct_compact drops NULLs, so a CASE with no ELSE omits the whole
        -- line instead of leaving a dangling "Genres:" label with nothing after it
        array_to_string(
            array_construct_compact(
                case
                    when m.title is null then null
                    when m.release_date is not null
                        then m.title || ' (' || year(m.release_date) || ')'
                    else m.title
                end,
                'Type: ' || case when m.media_type = 'tv' then 'TV series' else 'Film' end,
                case
                    when m.original_title is not null and m.original_title != m.title
                        then 'Original title: ' || m.original_title
                end,
                case when g.genre_list is not null then 'Genres: ' || g.genre_list end,
                case when d.director_list is not null then 'Director: ' || d.director_list end,
                case when c.cast_list is not null then 'Cast: ' || c.cast_list end,
                case when k.keyword_list is not null then 'Keywords: ' || k.keyword_list end,
                case when nullif(trim(m.tagline), '') is not null
                    then 'Tagline: ' || trim(m.tagline) end,
                case when nullif(trim(m.overview), '') is not null
                    then 'Overview: ' || trim(m.overview) end
            ),
            '\n'
        ) as document
    from {{ ref('dim_media') }} m
    left join genres    g on g.media_key = m.media_key
    left join keywords  k on k.media_key = m.media_key
    left join directors d on d.media_key = m.media_key
    left join top_cast  c on c.media_key = m.media_key
)

select
    media_key,
    media_type,
    tmdb_id,
    title,
    document,
    md5(document) as document_hash
from assembled
-- A title with nothing but a "Type:" line carries no signal and would waste a
-- Cortex call; embedding NULL errors outright. Require some real content.
where length(document) > 0
  and (
      document like '%Overview:%'
      or document like '%Genres:%'
      or document like '%Keywords:%'
  )
