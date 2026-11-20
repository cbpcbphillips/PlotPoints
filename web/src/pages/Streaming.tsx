import { useQueries, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Navigate } from 'react-router-dom'
import { FilmLink, PosterLink } from '../components/FilmLink'
import { Poster } from '../components/Poster'
import { Ad, Shell } from '../components/Shell'
import { Gauge, Sig } from '../components/Signals'
import { ErrorNote, Loading } from '../components/States'
import { api } from '../lib/api'
import { tmdbWatchUrl } from '../lib/format'
import { effectiveFilms, useProfile, type Profile } from '../lib/profile'
import type { Result } from '../lib/types'

const KEY = 'pp-services'
const SHOWN = 12 // the most widely available services; the long tail is mostly Amazon channels
const PER_SERVICE = 20 // each service contributes its own top 20, ranked with the filter inside
// Live-TV bundles carry films only as a sideline; they would crowd out the services people pick.
const LIVE_TV = new Set([
  'YouTube TV',
  'fuboTV',
  'FXNow',
  'Philo',
  'Sling TV',
  'tru TV',
  'TBS',
  'TNT',
  'Howdy',
  'MovieSphere+',
])

function readServices(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? '[]')
    return Array.isArray(v) ? v.filter((x) => typeof x === 'string') : []
  } catch {
    return []
  }
}

export interface Pick {
  r: Result
  services: string[]
}

/** Union of each chosen service's top list, best score first; a film notes every service it is on. */
export function mergePicks(chosen: string[], lists: (Result[] | undefined)[]): Pick[] {
  const byId = new Map<number, Pick>()
  chosen.forEach((svc, i) => {
    for (const r of lists[i] ?? []) {
      const have = byId.get(r.tmdb_id)
      if (have) have.services.push(svc)
      else byId.set(r.tmdb_id, { r, services: [svc] })
    }
  })
  return [...byId.values()].sort((a, b) => b.r.score - a.r.score || a.r.rank - b.r.rank)
}

export function Streaming() {
  const { profile } = useProfile()
  if (!profile) return <Navigate to="/" replace />
  return <StreamingFor profile={profile} />
}

function StreamingFor({ profile }: { profile: Profile }) {
  const meta = useQuery({ queryKey: ['meta'], queryFn: api.meta, staleTime: Infinity })
  const [chosen, setChosen] = useState<string[]>(readServices)
  const [skipped, setSkipped] = useState(0)
  const [leaving, setLeaving] = useState(false)

  const lists = useQueries({
    queries: chosen.map((svc) => ({
      queryKey: [
        'recommend-service',
        profile.importedAt,
        profile.matched,
        profile.notForMe.join(','),
        svc,
      ],
      queryFn: () =>
        api.recommend({
          members: [{ name: profile.name, films: effectiveFilms(profile) }],
          providers: [svc],
          limit: PER_SERVICE,
        }),
    })),
  })
  const pending = lists.some((l) => l.isPending)
  const failed = lists.find((l) => l.isError)
  const picks = mergePicks(
    chosen,
    lists.map((l) => l.data?.results),
  )
  const at = picks.slice(skipped, skipped + 3)

  const toggle = (name: string) => {
    const next = chosen.includes(name) ? chosen.filter((c) => c !== name) : [...chosen, name]
    setChosen(next)
    setSkipped(0)
    try {
      localStorage.setItem(KEY, JSON.stringify(next))
    } catch {
      /* the selection just will not persist */
    }
  }
  const advance = () => {
    setLeaving(true)
    window.setTimeout(() => {
      setSkipped((n) => n + 1)
      setLeaving(false)
    }, 320)
  }

  const services = (meta.data?.providers ?? [])
    .map((p) => p.name)
    .filter((n) => !LIVE_TV.has(n))
    .slice(0, SHOWN)

  return (
    <Shell title="Streaming">
      <section className="pagehead">
        <h1>Streaming</h1>
      </section>

      <Ad kind="leaderboard" />
      {meta.isPending && <Loading what="services" />}
      {meta.isError && <ErrorNote error={meta.error} retry={() => meta.refetch()} />}
      {meta.data && (
        <div className="svc" role="group" aria-label="Your streaming services">
          {services.map((name) => (
            <button
              key={name}
              type="button"
              aria-pressed={chosen.includes(name)}
              onClick={() => toggle(name)}
            >
              {name}
            </button>
          ))}
        </div>
      )}

      <div className="deck">
        <div>
          {chosen.length === 0 && (
            <div className="empty">Pick a service above to see your best matches on it.</div>
          )}
          {chosen.length > 0 && pending && <Loading />}
          {failed?.error && <ErrorNote error={failed.error} retry={() => failed.refetch()} />}
          {chosen.length > 0 && !pending && !failed && at.length === 0 && (
            <div className="empty">
              {picks.length === 0 ? (
                'Nothing in your matches streams there right now.'
              ) : (
                <>
                  That is everything on your services.{' '}
                  <button className="btn secondary" type="button" onClick={() => setSkipped(0)}>
                    Start over
                  </button>
                </>
              )}
            </div>
          )}
          {at.length > 0 && (
            <div className="stack">
              {at.map(({ r, services: on }, i) => (
                <article
                  key={r.media_key}
                  className={`panel card p${i}${i === 0 && leaving ? ' gone' : ''}`}
                  style={{ zIndex: 3 - i }}
                  // the cards peeking out behind the top one are decoration: not reachable by keyboard
                  inert={i > 0}
                >
                  <div className="pw">
                    <PosterLink id={r.tmdb_id}>
                      <Poster id={r.tmdb_id} title={r.title} path={r.poster_path} />
                    </PosterLink>
                  </div>
                  <div>
                    <p className="eyebrow m-0">
                      {skipped + i + 1} of {picks.length} · {on.join(' · ')}
                    </p>
                    <h2>
                      <FilmLink id={r.tmdb_id}>{r.title}</FilmLink>
                    </h2>
                    <p className="m-0 text-muted">
                      {[
                        r.year,
                        r.genres.slice(0, 2).join(', '),
                        r.runtime && `${r.runtime} min`,
                        r.tmdb_rating != null && `TMDB ${r.tmdb_rating.toFixed(1)}`,
                      ]
                        .filter(Boolean)
                        .join(' · ')}
                    </p>
                    <div className="my-3.5">
                      <Gauge score={r.score} />
                    </div>
                    <Sig r={r} />
                    {i === 0 && (
                      <div className="acts">
                        <a
                          className="btn primary lg"
                          href={tmdbWatchUrl(r.tmdb_id)}
                          target="_blank"
                          rel="noreferrer"
                        >
                          <span aria-hidden="true">▶</span> Watch
                        </a>
                        <button className="btn ghost" type="button" onClick={advance}>
                          Not tonight
                        </button>
                      </div>
                    )}
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>
        {picks.length > skipped + 1 && (
          <aside className="panel queue">
            <p className="label m-0">Up next</p>
            {picks.slice(skipped + 1, skipped + 6).map(({ r }) => (
              <div key={r.media_key} className="cc">
                <PosterLink id={r.tmdb_id}>
                  <Poster id={r.tmdb_id} title={r.title} path={r.poster_path} small />
                </PosterLink>
                <div>
                  <b>
                    <FilmLink id={r.tmdb_id}>{r.title}</FilmLink>
                  </b>
                  <small>{r.year}</small>
                  <span className="pc">{r.score.toFixed(1)} score</span>
                </div>
              </div>
            ))}
          </aside>
        )}
      </div>
      <Ad kind="infeed" />
    </Shell>
  )
}
