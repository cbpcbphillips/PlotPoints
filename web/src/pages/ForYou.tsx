import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { Link, Navigate } from 'react-router-dom'
import { Backdrop } from '../components/Backdrop'
import { FilmCard } from '../components/FilmCard'
import { FilmLink } from '../components/FilmLink'
import { Poster } from '../components/Poster'
import { Shell } from '../components/Shell'
import { Gauge, Sig, Stars } from '../components/Signals'
import { ErrorNote, Loading } from '../components/States'
import { api } from '../lib/api'
import { prettyDate, tmdbWatchUrl } from '../lib/format'
import { effectiveFilms, useProfile, type Profile } from '../lib/profile'
import type { Enjoyed, Result } from '../lib/types'

const FIRST_PAGE = 20 // the top pick, the reel, and the sample the "because you enjoyed" row uses
const PAGE = 10
const BRANCH_OUT = 12 // films in the varied second row

/** Recommendations for the current profile, paged. */
export function useRecommendations(
  profile: Profile,
  providers: string[] = [],
  enabled = true,
  firstPage = FIRST_PAGE,
) {
  return useInfiniteQuery({
    queryKey: [
      'recommend',
      profile.importedAt,
      profile.matched,
      profile.notForMe.join(','),
      providers.join('|'),
      firstPage,
    ],
    initialPageParam: 0,
    enabled,
    queryFn: ({ pageParam }) =>
      api.recommend({
        members: [{ name: profile.name, films: effectiveFilms(profile) }],
        providers,
        offset: pageParam,
        limit: pageParam === 0 ? firstPage : PAGE,
        bundle: true,
        branch_out: pageParam === 0 ? BRANCH_OUT : 0,
      }),
    getNextPageParam: (last, pages) =>
      last.has_more ? pages.reduce((n, p) => n + p.results.length, 0) : undefined,
  })
}

const LABELS = ['Closest film you rated', 'Second closest', 'Third closest']

function Hero({
  r,
  asOf,
  onNope,
}: {
  r: Result
  asOf: string | undefined
  onNope: () => void
}) {
  return (
    <section className="hero" aria-labelledby="pick">
      <div className="lb">
        <Backdrop path={r.backdrop_path} />
      </div>
      <div className="hero-body">
        <div className="pwrap">
          <Poster id={r.tmdb_id} title={r.title} path={r.poster_path} />
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
                <span key={g} className="chip">
                  {g}
                </span>
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
 * The best film outside the franchise the list leans on. This is franchise diversity, not the
 * "step outside your niche" pick the roadmap describes (decision 5c); the copy says only what it is.
 */
function Beyond({ top, other }: { top: Result; other: Result }) {
  return (
    <aside className="panel">
      <span className="tag">Beyond {top.franchise}</span>
      <h2>Best outside the franchise</h2>
      <div className="sp">
        <Poster id={other.tmdb_id} title={other.title} path={other.poster_path} />
        <div>
          <b className="font-title">
            <FilmLink id={other.tmdb_id}>{other.title}</FilmLink>
          </b>
          <div className="meta">
            {other.year && <span>{other.year}</span>}
            {other.runtime && <span>{other.runtime} min</span>}
          </div>
          <p>
            {other.match}% match. The highest-ranked film outside the franchise your list leans on.
          </p>
        </div>
      </div>
    </aside>
  )
}

function EnjoyedCard({ e }: { e: Enjoyed }) {
  return (
    <figure className="fc m-0">
      <div className="pw">
        <Poster id={e.tmdb_id} title={e.title} path={e.poster_path} />
      </div>
      <figcaption>
        <b>
          <FilmLink id={e.tmdb_id}>{e.title}</FilmLink>
        </b>
        <small>{e.year}</small>
        {e.rating != null && <Stars rating={e.rating} />}
        <small>{e.avg_match}% avg match</small>
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
  const meta = useQuery({ queryKey: ['meta'], queryFn: api.meta, staleTime: Infinity })
  const branchOut = q.data?.pages[0].branch_out ?? []
  const inBranchOut = new Set(branchOut.map((r) => r.tmdb_id))
  // a later page can reach films the branch-out row already shows; show each once
  const results = (q.data?.pages.flatMap((p) => p.results) ?? []).filter(
    (r, i) => i === 0 || !inBranchOut.has(r.tmdb_id),
  )
  const [top, ...rest] = results
  const enjoyed = q.data?.pages[0].enjoyed ?? []
  const ratings = new Map(profile.films.map((f) => [f.tmdb_id, f.rating]))
  const outside = top?.franchise ? rest.find((x) => x.franchise !== top.franchise) : undefined

  return (
    <Shell>
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
            <div className="two" style={outside ? undefined : { gridTemplateColumns: '1fr' }}>
              <Why r={top} ratings={ratings} />
              {outside && <Beyond top={top} other={outside} />}
            </div>

            {enjoyed.length > 0 && (
              <>
                <h2 className="sec">
                  Because you <em>enjoyed</em>
                </h2>
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
            {branchOut.length > 0 && (
              <>
                <h2 className="sec">
                  Branch <em>out</em>
                </h2>
                <p className="m-0 mb-3 max-w-[62ch] text-sm text-muted">
                  Still drawn from your taste, but spread away from everything above, with no series
                  repeated.
                </p>
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
