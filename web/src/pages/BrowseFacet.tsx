import { useQuery } from '@tanstack/react-query'
import { Link, Navigate, useLocation, useNavigate, useParams } from 'react-router-dom'
import { FilmCard } from '../components/FilmCard'
import { PeopleSearch } from '../components/PeopleSearch'
import { Ad, Shell } from '../components/Shell'
import { ErrorNote, Loading, PageTitle } from '../components/States'
import { api } from '../lib/api'
import {
  KIND_LABEL,
  facetTitle,
  facetsFromUrl,
  facetsPath,
  parseFacetKind,
  withFacet,
  withoutKind,
} from '../lib/browse'
import { useProfile, type Profile } from '../lib/profile'
import type { Facet } from '../lib/types'
import { useRecommendations } from './ForYou'

/**
 * `/browse/:kind/:value` (plus `?era=1990` and so on for more filters): the films you have not
 * seen that match every filter, closest to your taste first.
 */
export function BrowseFacet() {
  const { profile } = useProfile()
  const { kind: rawKind, value = '' } = useParams()
  const { search } = useLocation()
  const kind = parseFacetKind(rawKind)
  if (!profile) return <Navigate to="/" replace />
  if (!kind || !value) return <Navigate to="/browse" replace />
  return <FacetResults profile={profile} facets={facetsFromUrl(kind, value, search)} />
}

/** The active filters, each one a link that takes it off. */
function ActiveFilters({ facets }: { facets: Facet[] }) {
  return (
    <ul className="chips m-0 mt-3 list-none p-0" aria-label="Active filters">
      {facets.map((f) => {
        const name = facetTitle(f.kind, f.value)
        return (
          <li key={f.kind}>
            <Link
              to={facetsPath(withoutKind(facets, f.kind))}
              className="chip sel"
              aria-label={`${KIND_LABEL[f.kind]}: ${name}. Remove this filter`}
            >
              <span className="text-muted">{KIND_LABEL[f.kind]}:</span> {name}{' '}
              <span aria-hidden="true">&times;</span>
            </Link>
          </li>
        )
      })}
    </ul>
  )
}

/** Pick another genre or decade, or search for a director or actor, to narrow the list. */
function NarrowDown({ facets }: { facets: Facet[] }) {
  const navigate = useNavigate()
  const lists = useQuery({ queryKey: ['facets'], queryFn: api.facets, staleTime: Infinity })
  const current = (kind: Facet['kind']) => facets.find((f) => f.kind === kind)?.value ?? ''
  const pick = (kind: Facet['kind'], value: string) =>
    navigate(facetsPath(value ? withFacet(facets, { kind, value }) : withoutKind(facets, kind)))
  const selectClass =
    'mt-1 min-h-11 w-full rounded-[10px] border-[1.5px] border-field bg-bg px-3 text-base text-ink'
  return (
    <details className="panel mt-4" open={facets.length < 2}>
      <summary className="cursor-pointer text-lg font-bold">Narrow it down</summary>
      <div className="mt-3 grid gap-4 sm:max-w-xl sm:grid-cols-2">
        <div>
          <label htmlFor="nd-genre" className="text-sm text-muted">
            Genre
          </label>
          <select
            id="nd-genre"
            className={selectClass}
            value={current('genre')}
            onChange={(e) => pick('genre', e.target.value)}
          >
            <option value="">Any genre</option>
            {lists.data?.genres.map((g) => (
              <option key={g.name} value={g.name}>
                {g.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="nd-era" className="text-sm text-muted">
            Decade
          </label>
          <select
            id="nd-era"
            className={selectClass}
            value={current('era') ? String(Math.floor(parseInt(current('era'), 10) / 10) * 10) : ''}
            onChange={(e) => pick('era', e.target.value)}
          >
            <option value="">Any decade</option>
            {lists.data?.decades.map((d) => (
              <option key={d.decade} value={d.decade}>
                {d.decade}s
              </option>
            ))}
          </select>
        </div>
      </div>
      <PeopleSearch
        kind="director"
        label="Director"
        headingLevel={3}
        className="mt-5"
        hrefFor={(n) => facetsPath(withFacet(facets, { kind: 'director', value: n }))}
      />
      <PeopleSearch
        kind="actor"
        label="Actor"
        headingLevel={3}
        className="mt-5"
        hrefFor={(n) => facetsPath(withFacet(facets, { kind: 'actor', value: n }))}
      />
    </details>
  )
}

function FacetResults({ profile, facets }: { profile: Profile; facets: Facet[] }) {
  const q = useRecommendations(profile, [], true, 30, facets)
  const first = q.data?.pages[0]
  const named = first?.facet?.facets ?? facets
  const name = named.map((f) => facetTitle(f.kind, f.value)).join(' · ')
  const results = q.data?.pages.flatMap((p) => p.results) ?? []
  const total = first?.facet?.total

  return (
    <Shell title={`${name} · Browse`}>
      <p className="m-0 pt-6 text-sm">
        <Link to="/browse">Browse</Link> / {named.map((f) => KIND_LABEL[f.kind]).join(' + ')}
      </p>
      <PageTitle title={name}>
        {total == null
          ? undefined
          : total === 0
            ? 'No films in the catalog match all of these.'
            : `${total.toLocaleString()} ${total === 1 ? 'film matches' : 'films match'} in the catalog. These are the ones you have not seen, closest to your taste first.`}
      </PageTitle>
      <ActiveFilters facets={named} />
      <NarrowDown facets={named} />
      <Ad kind="leaderboard" />

      {q.isPending && <Loading what={`${name} films`} />}
      {q.isError && <ErrorNote error={q.error} retry={() => q.refetch()} />}
      {first && total === 0 && (
        <p className="empty mt-4" role="status">
          Nothing is in all of those at once. Take one filter off, above, to widen it.
        </p>
      )}
      {first && total !== 0 && results.length === 0 && (
        <p className="empty mt-4" role="status">
          You have seen everything we would suggest here.
        </p>
      )}
      {results.length > 0 && (
        <div className="fgrid mt-4">
          {results.map((r) => (
            <FilmCard key={r.media_key} r={r} rankLabel="in this list" />
          ))}
        </div>
      )}
      {q.hasNextPage && (
        <div className="flex justify-center pt-6">
          <button
            type="button"
            className="btn secondary lg"
            disabled={q.isFetchingNextPage}
            onClick={() => q.fetchNextPage()}
          >
            {q.isFetchingNextPage ? 'Loading…' : 'Show 10 more'}
          </button>
        </div>
      )}
      <Ad kind="infeed" />
    </Shell>
  )
}
