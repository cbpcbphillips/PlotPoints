import { useQuery } from '@tanstack/react-query'
import { Fragment } from 'react'
import { Link, Navigate, useLocation, useParams } from 'react-router-dom'
import { FilmCard } from '../components/FilmCard'
import { PeopleSearch } from '../components/PeopleSearch'
import { Ad, Shell } from '../components/Shell'
import { ErrorNote, Loading, PageTitle } from '../components/States'
import { api } from '../lib/api'
import {
  KIND_LABEL,
  addValue,
  facetTitle,
  facetsFromUrl,
  facetsPath,
  hasMode,
  hasValue,
  parseFacetKind,
  removeValue,
  setMode,
  valueTitle,
} from '../lib/browse'
import { useProfile, type Profile } from '../lib/profile'
import type { Facet, FacetKind } from '../lib/types'
import { useRecommendations } from './ForYou'

/**
 * `/browse/:kind/:value` (plus more values and kinds in the query string): the films you have
 * not seen that match every filter, closest to your taste first.
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

/** The same page with this value switched on or off. */
const toggled = (facets: Facet[], kind: FacetKind, value: string) =>
  facetsPath(
    hasValue(facets, kind, value)
      ? removeValue(facets, kind, value)
      : addValue(facets, kind, value),
  )

/** The active filters: each value a link that takes it off, and an all-of / any-of switch. */
function ActiveFilters({ facets }: { facets: Facet[] }) {
  return (
    <ul className="m-0 mt-3 grid list-none gap-2 p-0" aria-label="Active filters">
      {facets.map((f) => (
        <li key={f.kind} className="flex flex-wrap items-center gap-2">
          <span className="text-sm text-muted">{KIND_LABEL[f.kind]}:</span>
          {f.values.map((v, i) => (
            <Fragment key={v}>
              {i > 0 && (
                <span className="text-sm text-muted">
                  {f.mode === 'any' || f.kind === 'era' ? 'or' : 'and'}
                </span>
              )}
              <Link
                to={facetsPath(removeValue(facets, f.kind, v))}
                className="chip sel"
                aria-label={`${KIND_LABEL[f.kind]}: ${valueTitle(f.kind, v)}. Remove this filter`}
              >
                {valueTitle(f.kind, v)} <span aria-hidden="true">&times;</span>
              </Link>
            </Fragment>
          ))}
          {hasMode(f) && (
            <span
              role="group"
              aria-label={`How ${KIND_LABEL[f.kind].toLowerCase()} filters combine`}
            >
              <span className="mr-1.5 text-sm text-muted">Match</span>
              {(['all', 'any'] as const).map((m) => (
                <Link
                  key={m}
                  to={facetsPath(setMode(facets, f.kind, m))}
                  className={`chip${f.mode === m ? ' sel' : ''} mr-1.5`}
                  aria-current={f.mode === m ? 'true' : undefined}
                >
                  {m === 'all' ? 'all of them' : 'any of them'}
                </Link>
              ))}
            </span>
          )}
        </li>
      ))}
    </ul>
  )
}

/** Toggle more genres or decades, or search for themes, directors and actors, to change the list. */
function NarrowDown({ facets }: { facets: Facet[] }) {
  const lists = useQuery({ queryKey: ['facets'], queryFn: api.facets, staleTime: Infinity })
  const open = facets.reduce((n, f) => n + f.values.length, 0) < 3
  const search = (kind: 'keyword' | 'director' | 'actor', label: string) => (
    <PeopleSearch
      kind={kind}
      label={label}
      headingLevel={3}
      className="mt-5"
      hrefFor={(n) => toggled(facets, kind, n)}
      isSelected={(n) => hasValue(facets, kind, n)}
    />
  )
  return (
    <details className="panel mt-4" open={open}>
      <summary className="cursor-pointer text-lg font-bold">Change the filters</summary>
      <p className="m-0 mt-2 max-w-[62ch] text-sm text-muted">
        Pick more than one genre, decade, theme, director or actor. With two or more of the same
        kind, choose whether a film must match all of them (Romance and Comedy) or any of them
        (Drama or Thriller).
      </p>
      <h3 className="m-0 mt-4 text-lg font-bold">Genre</h3>
      <div className="chips mt-2">
        {lists.data?.genres.map((g) => (
          <Link
            key={g.name}
            to={toggled(facets, 'genre', g.name)}
            className={`chip${hasValue(facets, 'genre', g.name) ? ' sel' : ''}`}
            aria-current={hasValue(facets, 'genre', g.name) ? 'true' : undefined}
          >
            {g.name}
          </Link>
        ))}
      </div>
      <h3 className="m-0 mt-5 text-lg font-bold">Decade</h3>
      <div className="chips mt-2">
        {lists.data?.decades.map((d) => (
          <Link
            key={d.decade}
            to={toggled(facets, 'era', String(d.decade))}
            className={`chip${hasValue(facets, 'era', String(d.decade)) ? ' sel' : ''}`}
            aria-current={hasValue(facets, 'era', String(d.decade)) ? 'true' : undefined}
          >
            {d.decade}s
          </Link>
        ))}
      </div>
      {search('keyword', 'Theme')}
      {search('director', 'Director')}
      {search('actor', 'Actor')}
    </details>
  )
}

function FacetResults({ profile, facets }: { profile: Profile; facets: Facet[] }) {
  const q = useRecommendations(profile, [], true, 30, facets)
  const first = q.data?.pages[0]
  const named = first?.facet?.facets ?? facets
  const name = named.map(facetTitle).join(' · ')
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
      <ActiveFilters facets={facets} />
      <NarrowDown facets={facets} />
      <Ad kind="leaderboard" />

      {q.isPending && <Loading what={`${name} films`} />}
      {q.isError && <ErrorNote error={q.error} retry={() => q.refetch()} />}
      {first && total === 0 && (
        <p className="empty mt-4" role="status">
          Nothing is in all of those at once. Take a filter off, or switch a pair to &ldquo;any of
          them&rdquo;, to widen it.
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
