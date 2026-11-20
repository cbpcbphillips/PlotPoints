-- The text we embed: one labeled document per title, built from the star schema
-- rather than by re-flattening `record`, so it always agrees with the dims/bridges
-- the marts are tested against.
--
-- Field set (roadmap "Decisions made" #4): theme *and* people -- genres, keywords,
-- overview and tagline carry subject matter; director and top cast carry the
-- affinity that drives a lot of real taste ("anything by Fincher").
--
-- The title is deliberately NOT in the document, and it is stripped from the overview and tagline
-- (see macros/strip_title.sql). Embedding models weight repeated surface words, so with the title
-- present neighbours were films whose *titles* share a word (Moneyball -> Hardball, Rollerball;
-- Good Will Hunting -> Happy Hunting, MouseHunt) instead of films about the same thing.
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

-- the title's words, edge punctuation trimmed and regex-escaped. Short words and stopwords are kept
-- out of the *pair* pattern so a phrase like "the dark" is never rewritten in an overview.
title_words as (
    select
        m.media_key,
        f.index as idx,
        regexp_replace(
            regexp_replace(f.value::string, '^[^[:alnum:]]+|[^[:alnum:]]+$', ''),
            $$([.^$*+?()\[\]{}|\\-])$$, $$\\\1$$
        ) as word,
        (
            length(regexp_replace(f.value::string, '[^[:alnum:]]', '')) >= 3
            and lower(regexp_replace(f.value::string, '[^[:alnum:]]', '')) not in (
                'the', 'and', 'for', 'with', 'from', 'into', 'of', 'in', 'on', 'to', 'at', 'by'
            )
        ) as significant
    from {{ ref('dim_media') }} m,
         lateral flatten(input => split(trim(m.title), ' ')) f
    where regexp_like(f.value::string, '.*[[:alnum:]].*')
),

title_patterns as (
    select
        media_key,
        count(*) as n_words,
        listagg(word, $$[^[:alnum:]]+$$) within group (order by idx) as full_pattern,
        -- nullif: listagg over no usable pairs returns '' rather than NULL, and an empty pattern
        -- matches at every word boundary, which would wreck the text
        nullif(
            listagg(
                case
                    when significant and next_significant
                        then word || $$[^[:alnum:]]+$$ || next_word
                end,
                '|'
            ) within group (order by idx),
            ''
        ) as pair_pattern
    from (
        select
            media_key,
            idx,
            word,
            significant,
            lead(word) over (partition by media_key order by idx) as next_word,
            lead(significant) over (partition by media_key order by idx) as next_significant
        from title_words
    )
    group by media_key
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
                'Type: ' || case when m.media_type = 'tv' then 'TV series' else 'Film' end,
                case when g.genre_list is not null then 'Genres: ' || g.genre_list end,
                case when d.director_list is not null then 'Director: ' || d.director_list end,
                case when c.cast_list is not null then 'Cast: ' || c.cast_list end,
                case when k.keyword_list is not null then 'Keywords: ' || k.keyword_list end,
                case when nullif(trim(m.tagline), '') is not null
                    then 'Tagline: '
                        || {{ strip_title('trim(m.tagline)', 'tp.full_pattern', 'tp.pair_pattern') }}
                end,
                case when nullif(trim(m.overview), '') is not null
                    then 'Overview: '
                        || {{ strip_title('trim(m.overview)', 'tp.full_pattern', 'tp.pair_pattern') }}
                end
            ),
            '\n'
        ) as document
    from {{ ref('dim_media') }} m
    left join genres    g on g.media_key = m.media_key
    left join keywords  k on k.media_key = m.media_key
    left join directors d on d.media_key = m.media_key
    left join top_cast  c on c.media_key = m.media_key
    -- one-word titles get no pattern (see strip_title.sql)
    left join title_patterns tp on tp.media_key = m.media_key and tp.n_words >= 2
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
