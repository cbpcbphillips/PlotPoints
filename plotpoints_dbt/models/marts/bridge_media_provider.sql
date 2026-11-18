-- Media <-> US subscription (flatrate) streaming provider, many-to-many.
--
-- TMDB lists 209 raw provider names, mostly one service sold several ways: "Netflix" and
-- "Netflix Standard with Ads", "HBO Max" and "HBO Max Amazon Channel". For "I have Netflix, what can
-- I watch?" those are one service, so each raw name is reduced to a `provider_group`: strip the
-- tier/channel suffix, then apply seeds/provider_aliases.csv for brands TMDB spells two ways.
-- `via_channel` records that the title is only offered inside an Amazon/Apple/Roku add-on channel.

with flat as (
    select distinct
        m.media_key,
        p.value::string as provider_name
    from {{ ref('int_media') }} m,
         lateral flatten(input => m.record:watch_providers:flatrate) p
    where p.value is not null
),

stripped as (
    select
        media_key,
        provider_name,
        provider_name ilike '%channel' as via_channel,
        trim(regexp_replace(
            provider_name,
            ' +(Amazon Channel|Apple TV channel|Roku Premium Channel|Standard with Ads|with Ads|Essential|Premium Plus|Premium)$',
            '', 1, 1, 'i'
        )) as brand
    from flat
)

select distinct
    s.media_key,
    s.provider_name,
    coalesce(a.provider_group, s.brand) as provider_group,
    s.via_channel
from stripped s
left join {{ ref('provider_aliases') }} a on lower(s.brand) = a.brand
