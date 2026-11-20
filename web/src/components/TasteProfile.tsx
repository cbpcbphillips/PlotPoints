import { useQuery } from '@tanstack/react-query'
import type { CSSProperties } from 'react'
import { api } from '../lib/api'
import { stillMissing } from '../lib/importing'
import type { Profile } from '../lib/profile'
import type { MissingFilm, ProfileStats, Share } from '../lib/types'
import { ErrorNote, Loading } from './States'

const HALF = (r: number) => (Number.isInteger(r) ? String(r) : `${Math.floor(r)}½`.replace(/^0/, ''))

function Bars({ items }: { items: Share[] }) {
  const max = Math.max(...items.map((i) => i.count), 1)
  return (
    <div className="gbars">
      {items.map((i) => (
        <div key={i.name}>
          <span>{i.name}</span>
          <span className="bar-h">
            <i style={{ width: `${Math.round((100 * i.count) / max)}%` }} />
          </span>
          <span>{i.share}%</span>
        </div>
      ))}
    </div>
  )
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-3 border-t border-line py-2.5">
      <span className="text-muted">{k}</span>
      <b className="text-right">{v}</b>
    </div>
  )
}

const REASON: Record<MissingFilm['reason'], string> = {
  not_in_catalog: 'Not in the catalog yet. Added on the next update',
  tv: 'TV series',
  not_found: 'Not found on TMDB',
}

/** The films this history holds that the profile cannot use yet, each with the reason. */
function CantUse({ films }: { films: MissingFilm[] }) {
  if (!films.length) return null
  return (
    <div className="panel mt-4">
      <div className="flex items-baseline justify-between">
        <h2>Films we can&rsquo;t use yet</h2>
        <span className="label">{films.length}</span>
      </div>
      <ul className="m-0 mt-2 list-none p-0">
        {films.map((m) => (
          <li
            key={`${m.tmdb_id ?? m.title}|${m.year}`}
            className="flex flex-wrap justify-between gap-x-4 border-t border-line py-2.5"
          >
            <span>
              <b>{m.title}</b>
              {m.year && <span className="text-muted"> ({m.year})</span>}
            </span>
            <span className="text-sm text-muted">
              {REASON[m.reason]}
              {m.votes != null && ` · ${m.votes} TMDB votes`}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function Body({ s, missing }: { s: ProfileStats; missing: MissingFilm[] }) {
  const max = Math.max(...s.histogram.map((h) => h.count), 1)
  return (
    <>
      <div className="tiles">
        <div className="tile hl">
          <p className="label m-0">Films</p>
          <b>{s.films.toLocaleString()}</b>
        </div>
        <div className="tile">
          <p className="label m-0">Rated</p>
          <b>{s.rated.toLocaleString()}</b>
        </div>
        <div className="tile">
          <p className="label m-0">Average</p>
          <b>
            {s.average_rating != null ? (
              <>
                {s.average_rating.toFixed(1)} <span aria-hidden="true">★</span>
                <span className="sr-only"> out of 5</span>
              </>
            ) : (
              '–'
            )}
          </b>
        </div>
        <div className="tile">
          <p className="label m-0">Not in catalog</p>
          <b>{s.not_in_catalog.toLocaleString()}</b>
        </div>
      </div>

      <div className="panel mt-4">
        <div className="flex items-baseline justify-between">
          <h2>Your rating spread</h2>
          <span className="label">{s.rated.toLocaleString()} ratings</span>
        </div>
        <div className="hist" role="img" aria-label="Rating histogram">
          {s.histogram.map((h) => (
            <div key={h.rating}>
              <i style={{ '--v': Math.round((100 * h.count) / max) } as CSSProperties} />
              {HALF(h.rating)}
            </div>
          ))}
        </div>
        <p className="mb-0 mt-3 text-sm text-muted">
          Liked films (above 3★) pull hardest. Below 3★ steers matches away.
        </p>
      </div>

      <div className="mt-4 grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(250px,1fr))]">
        <div className="panel">
          <h2 className="mb-3">Top genres</h2>
          <Bars items={s.genres} />
        </div>
        <div className="panel">
          <h2 className="mb-3">Eras</h2>
          <Bars items={s.eras} />
        </div>
        <div className="panel">
          <h2 className="mb-1.5">At a glance</h2>
          {s.average_runtime != null && <Row k="Average runtime" v={`${s.average_runtime} min`} />}
          {s.top_series && (
            <Row k="Most-watched series" v={`${s.top_series.name} · ${s.top_series.count} films`} />
          )}
          {s.average_tmdb != null && (
            <Row k="Avg TMDB rating of your films" v={s.average_tmdb.toFixed(1)} />
          )}
          <Row k="Five-star films" v={String(s.five_star.length)} />
          {s.newest != null && s.oldest != null && (
            <Row k="Newest / oldest" v={`${s.newest} / ${s.oldest}`} />
          )}
        </div>
      </div>
      <CantUse films={stillMissing(missing, s.missing_ids)} />
    </>
  )
}

/** What the history says about taste: counts, rating spread, genres, eras, a few facts. */
export function TasteProfile({ profile }: { profile: Profile }) {
  const q = useQuery({
    queryKey: ['profile', profile.importedAt, profile.films.length],
    queryFn: () => api.profile(profile.films),
  })
  return (
    <section className="pt-2">
      <h2 className="sec">Your taste profile</h2>
      {profile.source === 'username' && (
        <p className="-mt-2 mb-3.5 text-sm text-muted">
          Built from the latest entries on your feed. An export fills it in properly.
        </p>
      )}
      {q.isPending && <Loading what="your profile" />}
      {q.isError && <ErrorNote error={q.error} retry={() => q.refetch()} />}
      {q.data && <Body s={q.data} missing={profile.missing ?? []} />}
    </section>
  )
}
