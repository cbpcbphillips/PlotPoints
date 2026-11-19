import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Navigate } from 'react-router-dom'
import { Poster } from '../components/Poster'
import { Shell } from '../components/Shell'
import { Gauge, Stars } from '../components/Signals'
import { ErrorNote, Loading } from '../components/States'
import { api } from '../lib/api'
import { effectiveFilms, useProfile, type Profile } from '../lib/profile'
import type { FranchiseGroup } from '../lib/types'

/** One film on a shelf: either a recommendation (unseen) or one the person has already seen. */
interface Entry {
  id: number
  key: string
  title: string
  year: number | null
  seen: boolean
  rating: number | null
  match: number | null
  score: number | null
  tmdb: number | null
  poster: string | null
  best: boolean
}

type Show = 'all' | 'unseen' | 'seen'
type Order = 'year' | 'score'

export function entriesOf(f: FranchiseGroup): Entry[] {
  const unseen: Entry[] = [f.best, ...f.others].map((r, i) => ({
    id: r.tmdb_id,
    key: r.media_key,
    title: r.title,
    year: r.year,
    seen: false,
    rating: null,
    match: r.match,
    score: r.score,
    tmdb: r.tmdb_rating,
    poster: r.poster_path,
    best: i === 0,
  }))
  const seen: Entry[] = f.seen.map((s) => ({
    id: s.tmdb_id,
    key: s.media_key,
    title: s.title,
    year: s.year,
    seen: true,
    rating: s.rating,
    match: null,
    score: null,
    tmdb: s.tmdb_rating,
    poster: s.poster_path,
    best: false,
  }))
  return [...unseen, ...seen]
}

/** Release order, or by ranking score with unseen films first and seen films by your rating. */
export function sortEntries(list: Entry[], order: Order): Entry[] {
  const byYear = (a: Entry, b: Entry) => (a.year ?? 0) - (b.year ?? 0) || a.title.localeCompare(b.title)
  if (order === 'year') return [...list].sort(byYear)
  return [...list].sort(
    (a, b) =>
      (b.score ?? -Infinity) - (a.score ?? -Infinity) ||
      (b.rating ?? 0) - (a.rating ?? 0) ||
      byYear(a, b),
  )
}

function Tag({ e }: { e: Entry }) {
  if (e.best) return <span className="ptag best">BEST {e.match}%</span>
  if (!e.seen) return null
  return e.rating ? (
    <span className="ptag rated">★ {e.rating}</span>
  ) : (
    <span className="ptag seen">✓ SEEN</span>
  )
}

function Shelf({ f, show, order }: { f: FranchiseGroup; show: Show; order: Order }) {
  const all = entriesOf(f)
  const years = all.map((e) => e.year).filter((y): y is number => y != null)
  const span = years.length ? `${Math.min(...years)}–${Math.max(...years)}` : ''
  const seenCount = all.filter((e) => e.seen).length
  const shown = sortEntries(all, order).filter(
    (e) => show === 'all' || (show === 'seen') === e.seen,
  )
  if (shown.length === 0) return null
  const best = f.best
  const byYear = sortEntries(all, 'year')

  return (
    <article className="panel shelf">
      <div className="feat">
        <h2>
          {f.franchise}
          <small>
            {all.length} films · {span}
          </small>
        </h2>
        <div className="prog">
          <div
            className="segs"
            role="img"
            aria-label={`${seenCount} of ${all.length} seen`}
          >
            {byYear.map((e) => (
              <i key={e.key} className={e.best ? 'best' : e.seen ? 'seen' : ''} />
            ))}
          </div>
          <span>
            <b>
              {seenCount} of {all.length}
            </b>{' '}
            seen · {all.length - seenCount} to go
          </span>
        </div>
        <div>
          <Poster id={best.tmdb_id} title={best.title} path={best.poster_path} />
        </div>
        <div className="bm">
          <span className="eyebrow">Best match · unseen</span>
          <b>{best.title}</b>
          <span className="text-[13px] text-muted">
            {best.year}
            {best.tmdb_rating != null && ` · TMDB ${best.tmdb_rating.toFixed(1)}`}
          </span>
          <Gauge score={best.score} />
        </div>
      </div>
      <div className="strip">
        <p className="label mb-2.5">
          In this franchise · {order === 'score' ? 'ranked by score' : 'release order'}
        </p>
        <div className="row">
          {shown.map((e) => (
            <figure key={e.key} className={`fc m-0${e.best ? ' best' : ''}${e.seen ? ' seen' : ''}`}>
              <div className="pw">
                <Tag e={e} />
                <Poster id={e.id} title={e.title} path={e.poster} small />
              </div>
              <figcaption>
                <b>{e.title}</b>
                <small>
                  {e.year}
                  {e.tmdb != null && ` · TMDB ${e.tmdb.toFixed(1)}`}
                </small>
                {e.seen ? (
                  e.rating ? (
                    <div className="mine">
                      <Stars rating={e.rating} />
                    </div>
                  ) : (
                    <small>seen, not rated</small>
                  )
                ) : (
                  <>
                    <span className="pct">{e.match}% match</span>
                    <small>score {e.score?.toFixed(1)}</small>
                  </>
                )}
              </figcaption>
            </figure>
          ))}
        </div>
      </div>
    </article>
  )
}

export function Franchises() {
  const { profile } = useProfile()
  if (!profile) return <Navigate to="/" replace />
  return <FranchisesFor profile={profile} />
}

const SHOWS: [Show, string][] = [
  ['all', 'All films'],
  ['unseen', 'Unseen only'],
  ['seen', 'Seen only'],
]
const ORDERS: [Order, string][] = [
  ['year', 'Release'],
  ['score', 'Score'],
]

function FranchisesFor({ profile }: { profile: Profile }) {
  const [show, setShow] = useState<Show>('all')
  const [order, setOrder] = useState<Order>('year')
  const q = useQuery({
    queryKey: ['franchises', profile.importedAt, profile.matched, profile.notForMe.join(',')],
    queryFn: () =>
      api.franchises({ members: [{ name: profile.name, films: effectiveFilms(profile) }] }),
  })

  return (
    <Shell>
      <section className="pagehead">
        <p className="eyebrow m-0">Your top 5 franchises</p>
        <h1>Franchises</h1>
      </section>
      {q.isPending && <Loading what="your franchises" />}
      {q.isError && <ErrorNote error={q.error} retry={() => q.refetch()} />}
      {q.data && (
        <>
          <div className="tools">
            <span className="label">Show</span>
            {SHOWS.map(([v, label]) => (
              <button
                key={v}
                type="button"
                className={`chip${show === v ? ' sel' : ''}`}
                aria-pressed={show === v}
                onClick={() => setShow(v)}
              >
                {label}
              </button>
            ))}
            <span className="label ml-3.5">Order</span>
            {ORDERS.map(([v, label]) => (
              <button
                key={v}
                type="button"
                className={`chip${order === v ? ' sel' : ''}`}
                aria-pressed={order === v}
                onClick={() => setOrder(v)}
              >
                {label}
              </button>
            ))}
          </div>
          {q.data.franchises.map((f) => (
            <Shelf key={f.franchise} f={f} show={show} order={order} />
          ))}
          {q.data.franchises.length === 0 && (
            <p className="empty">None of your top matches belong to a franchise yet.</p>
          )}
        </>
      )}
    </Shell>
  )
}
