import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { useEffect, useMemo } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { Backdrop } from '../components/Backdrop'
import { FilmCard } from '../components/FilmCard'
import { FilmLink, PosterLink } from '../components/FilmLink'
import { Poster } from '../components/Poster'
import { Ad, Shell } from '../components/Shell'
import { Gauge, Sig, Stars } from '../components/Signals'
import { ErrorNote, Loading } from '../components/States'
import { api } from '../lib/api'
import { browsePath } from '../lib/browse'
import { prettyDate, tmdbWatchUrl } from '../lib/format'
import { effectiveFilms, useProfile, type Profile } from '../lib/profile'
import { keyString, loadList, saveList } from '../lib/savedLists'
import type { Enjoyed, Facet, Result } from '../lib/types'

const FIRST_PAGE = 20 // the top pick, the reel, and the sample the "because you enjoyed" row uses
const PAGE = 10
const BRANCH_OUT = 12 // films in the varied second row

/**
 * Recommendations for the current profile, paged.
 *
 * The plain main list (no service filter, no browse filter, the standard first page) is also kept in
 * this browser: a returning visitor sees it straight away while a fresh one loads, which hides a
 * sleeping server. `showingSaved` is true until the fresh answer arrives.
 */
export function useRecommendations(
  profile: Profile,
  providers: string[] = [],
  enabled = true,
  firstPage = FIRST_PAGE,
  facets?: Facet[],
) {
  const queryKey = [
    'recommend',
    profile.importedAt,
    profile.matched,
    profile.notForMe.join(','),
    providers.join('|'),
    firstPage,
    facets?.map((f) => `${f.kind}:${f.mode}:${f.values.join('|')}`).join(',') ?? '',
  ]
  const key = keyString(queryKey)
  const mainList = providers.length === 0 && !facets?.length && firstPage === FIRST_PAGE
  const saved = useMemo(
    () => (mainList && enabled ? loadList(key) : null),
    [key, mainList, enabled],
  )

  const q = useInfiniteQuery({
    queryKey,
    initialPageParam: 0,
    enabled,
    // a saved list is shown at once but counts as old, so the page asks for a fresh one anyway
    ...(saved
      ? {
          initialData: { pages: [saved.page], pageParams: [0] },
          initialDataUpdatedAt: saved.savedAt,
        }
      : {}),
    queryFn: ({ pageParam }) =>
      api.recommend({
        members: [{ name: profile.name, films: effectiveFilms(profile) }],
        providers,
        offset: pageParam,
        limit: pageParam === 0 ? firstPage : PAGE,
        bundle: true,
        branch_out: pageParam === 0 && !facets?.length ? BRANCH_OUT : 0,
        facets,
      }),
    getNextPageParam: (last, pages) =>
      last.has_more ? pages.reduce((n, p) => n + p.results.length, 0) : undefined,
  })

  const first = q.data?.pages[0]
  useEffect(() => {
    if (mainList && q.isFetchedAfterMount && q.isSuccess && first) saveList(key, first)
  }, [key, mainList, q.isFetchedAfterMount, q.isSuccess, first])

  // only while a fresh list is actually on its way (a list saved a minute ago needs none)
  return Object.assign(q, {
    showingSaved: saved !== null && q.isFetching && !q.isFetchedAfterMount,
  })
}

const LABELS = ['Closest film you rated', 'Second closest', 'Third closest']

// Below these many liked films (rated above 3 stars, in the catalog) the taste profile is thin.
const FEW_LIKED = 15
const VERY_FEW_LIKED = 5

/** A heads-up that the picks rest on little: there is not much of a taste vector to sample. */
function ThinTaste({ liked, source }: { liked: number; source: Profile['source'] }) {
  if (liked >= FEW_LIKED) return null
  const veryFew = liked < VERY_FEW_LIKED
  return (
    <div
      role="status"
      className="mt-4 rounded-lg border border-line border-l-4 border-l-accent bg-surface px-4 py-3 text-sm"
    >
      <b>{veryFew ? 'Not much to go on yet.' : 'Your taste profile is still small.'}</b> These picks
      come from {liked === 1 ? 'one film' : `${liked} films`} you rated above 3 stars, so they will
      change a lot as you rate more.{' '}
      {source === 'username' && 'A username only brings in your latest 50 or so entries. '}
      <Link to="/import" className="font-semibold underline">
        {source === 'username' ? 'Import your full Letterboxd export' : 'Add more history'}
      </Link>{' '}
      for sharper matches.
    </div>
  )
}

function Hero({ r, asOf, onNope }: { r: Result; asOf: string | undefined; onNope: () => void }) {
  return (
    <section className="hero" aria-labelledby="pick">
      <div className="lb">
        <Backdrop path={r.backdrop_path} />
      </div>
      <div className="hero-body">
        <div className="pwrap">
          <PosterLink id={r.tmdb_id}>
            <Poster id={r.tmdb_id} title={r.title} path={r.poster_path} />
          </PosterLink>
        </div>
        <div className="txt">
          <p className="eyebrow m-0">Recommended</p>
          <h1 id="pick">
            <FilmLink id={r.tmdb_id}>{r.title}</FilmLink>
          </h1>
          <p className="meta m-0">
            {r.year && <span>{r.year}</span>}
            {r.runtime && <span>{r.runtime} min</span>}
          </p>
          {r.bundle && (
            <p className="m-0 mt-2 text-sm text-muted">
              Plus {r.bundle.more} more {r.bundle.franchise} films in your list.{' '}
              <Link to="/franchises" className="font-semibold text-inherit underline">
                See the series
              </Link>
            </p>
          )}
          {r.genres.length > 0 && (
            <div className="chips mt-3">
              {r.genres.map((g) => (
                <Link key={g} to={browsePath('genre', g)} className="chip">
                  {g}
                </Link>
              ))}
            </div>
          )}
          <Gauge score={r.score} />
          <Sig r={r} />
          <div className="chips">
            <a
              className="btn primary"
              href={tmdbWatchUrl(r.tmdb_id)}
              target="_blank"
              rel="noreferrer"
            >
              Where to watch
            </a>
            <button className="btn secondary" type="button" onClick={onNope}>
              Not for me
            </button>
          </div>
          {r.providers.length > 0 && (
            <p className="avail">
              <span className="label">Streaming (US)</span>
              {r.providers.slice(0, 4).map((p) => (
                <span key={p} className="chip">
                  {p}
                </span>
              ))}
              <span>{asOf ? `as of ${asOf} · ` : ''}via JustWatch</span>
            </p>
          )}
        </div>
      </div>
    </section>
  )
}

function Why({ r, ratings }: { r: Result; ratings: Map<number, number | null> }) {
  const because = r.members[0]?.because ?? []
  return (
    <section className="panel" aria-labelledby="why">
      <div className="why-head">
        <h2 id="why">Why this pick</h2>
        <span className="label">{because.length} films you rated</span>
      </div>
      <ol className="reasons">
        {because.map((b, i) => {
          const rating = ratings.get(b.tmdb_id) ?? null
          return (
            <li key={b.tmdb_id}>
              <div>
                <span className="award">{LABELS[i] ?? `Closest #${i + 1}`}</span>
                <p>
                  You {rating != null ? 'rated' : 'watched'} <b>{b.title}</b>{' '}
                  {rating != null && <Stars rating={rating} />}
                  <span className="sim">{b.match}% similar</span>
                </p>
              </div>
            </li>
          )
        })}
      </ol>
    </section>
  )
}

/**
 * A good film from a genre this person rarely rates, that still scores well for them. The server
 * picks it (scoring.wildcard_pick). The copy says what is true of it, and does not claim it is
 * similar to what they rated: that is the point of it.
 */
function Wildcard({ pick }: { pick: Result }) {
  const o = pick.outside
  return (
    <aside className="panel" aria-labelledby="wild">
      <h2 id="wild">Step outside your comfort zone</h2>
      <div className="sp">
        <PosterLink id={pick.tmdb_id}>
          <Poster id={pick.tmdb_id} title={pick.title} path={pick.poster_path} />
        </PosterLink>
        <div>
          <b className="font-title">
            <FilmLink id={pick.tmdb_id}>{pick.title}</FilmLink>
          </b>
          <div className="meta">
            {pick.year && <span>{pick.year}</span>}
            {pick.genres.length > 0 && <span>{pick.genres.slice(0, 2).join(', ')}</span>}
            {pick.tmdb_rating != null && <span>TMDB {pick.tmdb_rating.toFixed(1)}</span>}
          </div>
          {o && (
            <p>
              {o.genre ? (
                <>
                  {o.liked_in_genre === 0
                    ? `None of your ${o.liked_total} liked films are ${o.genre}.`
                    : `Only ${o.liked_in_genre} of your ${o.liked_total} liked ${o.liked_in_genre === 1 ? 'film is' : 'films are'} ${o.genre}.`}{' '}
                </>
              ) : null}
              It is well rated, and still scores in the top {o.top_percent}% of everything we could
              suggest for you.
            </p>
          )}
        </div>
      </div>
    </aside>
  )
}

function EnjoyedCard({ e }: { e: Enjoyed }) {
  return (
    <figure className="fc m-0">
      <div className="pw">
        <PosterLink id={e.tmdb_id}>
          <Poster id={e.tmdb_id} title={e.title} path={e.poster_path} />
        </PosterLink>
      </div>
      <figcaption>
        <b>
          <FilmLink id={e.tmdb_id}>{e.title}</FilmLink>
        </b>
        <small>{e.year}</small>
        {e.rating != null && <Stars rating={e.rating} />}
        <small>
          Behind {e.behind} of your top {e.of}
        </small>
      </figcaption>
    </figure>
  )
}

export function ForYou() {
  const { profile, markNotForMe } = useProfile()
  if (!profile) return <Navigate to="/" replace />
  return <ForYouFor profile={profile} onNope={markNotForMe} />
}

function ForYouFor({ profile, onNope }: { profile: Profile; onNope: (id: number) => void }) {
  const q = useRecommendations(profile)
  const meta = useQuery({
    queryKey: ['meta'],
    queryFn: api.meta,
    staleTime: Infinity,
  })
  const branchOut = q.data?.pages[0].branch_out ?? []
  const wildcard = q.data?.pages[0].wildcard ?? undefined
  const inBranchOut = new Set(branchOut.map((r) => r.tmdb_id))
  // a later page can reach films the branch-out row already shows; show each once
  const results = (q.data?.pages.flatMap((p) => p.results) ?? []).filter(
    (r, i) => i === 0 || !inBranchOut.has(r.tmdb_id),
  )
  const [top, ...others] = results
  // the comfort-zone pick has its own panel; do not list it again in the row below
  const rest = others.filter((r) => r.tmdb_id !== wildcard?.tmdb_id)
  const enjoyed = q.data?.pages[0].enjoyed ?? []
  const ratings = new Map(profile.films.map((f) => [f.tmdb_id, f.rating]))

  return (
    <Shell title="For you">
      <div className="pt-6">
        {q.isPending && <Loading />}
        {q.isError && <ErrorNote error={q.error} retry={() => q.refetch()} />}
        {top && (
          <>
            <Hero
              r={top}
              asOf={meta.data ? prettyDate(meta.data.providers_as_of) : undefined}
              onNope={() => onNope(top.tmdb_id)}
            />
            {q.showingSaved && (
              <p role="status" className="m-0 mt-3 text-sm text-muted">
                Showing your last list while we get a fresh one.
              </p>
            )}
            <ThinTaste liked={q.data?.pages[0].liked_films ?? 0} source={profile.source} />
            <Ad kind="leaderboard" />
            <div className="two" style={wildcard ? undefined : { gridTemplateColumns: '1fr' }}>
              <Why r={top} ratings={ratings} />
              {wildcard && <Wildcard pick={wildcard} />}
            </div>

            {enjoyed.length > 0 && (
              <>
                <h2 className="sec">
                  The films <em>shaping</em> your picks
                </h2>
                <p className="m-0 mb-3 max-w-[62ch] text-sm text-muted">
                  From everything you rated, these pull hardest on your recommendations.
                </p>
                <div className="row">
                  {enjoyed.map((e) => (
                    <EnjoyedCard key={e.media_key} e={e} />
                  ))}
                </div>
              </>
            )}

            <h2 className="sec">Other recommendations</h2>
            <div className="row">
              {rest.map((r) => (
                <FilmCard key={r.media_key} r={r} />
              ))}
            </div>
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
            {branchOut.length > 0 && (
              <>
                <h2 className="sec">
                  Branch <em>out</em>
                </h2>
                <div className="row">
                  {branchOut.map((r) => (
                    <FilmCard key={r.media_key} r={r} />
                  ))}
                </div>
              </>
            )}
            {q.data?.pages[0].unmatched_films ? (
              <p className="pt-8 text-center text-sm text-muted">
                {q.data.pages[0].unmatched_films} of your films are not in the catalog, so they
                could not be used.
              </p>
            ) : null}
          </>
        )}
      </div>
    </Shell>
  )
}
