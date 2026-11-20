import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { Backdrop } from '../components/Backdrop'
import { FilmLink, PosterLink } from '../components/FilmLink'
import { Poster } from '../components/Poster'
import { Ad, Shell } from '../components/Shell'
import { Stars } from '../components/Signals'
import { ErrorNote, Loading } from '../components/States'
import { ApiError, api } from '../lib/api'
import { browsePath, decadeOf } from '../lib/browse'
import { parseFilmId, prettyDate, runtimeLabel, tmdbWatchUrl } from '../lib/format'
import { effectiveFilms, useProfile } from '../lib/profile'
import type { ClosestFilm, FilmDetail, SimilarFilm } from '../lib/types'

function SimilarCard({ f }: { f: SimilarFilm }) {
  return (
    <figure className="fc m-0">
      <div className="pw">
        <PosterLink id={f.tmdb_id}>
          <Poster id={f.tmdb_id} title={f.title} path={f.poster_path} />
        </PosterLink>
      </div>
      <figcaption>
        <b>
          <FilmLink id={f.tmdb_id}>{f.title}</FilmLink>
        </b>
        <small>
          {f.year}
          {f.tmdb_rating != null && ` · TMDB ${f.tmdb_rating.toFixed(1)}`}
        </small>
        <small>{f.match}% similar</small>
      </figcaption>
    </figure>
  )
}

/**
 * The viewer's own films closest to this one, from the films already in their browser. Without an
 * import there is nothing to compare, so it offers the import; if the viewer has nothing rated
 * above three stars the API says so (422) and the block is simply left out.
 */
function ClosestToYou({ id }: { id: number }) {
  const { profile } = useProfile()
  const q = useQuery({
    // the import time stands for the contents, as it does for the recommendations
    queryKey: ['film-for-me', id, profile?.importedAt, profile?.notForMe.join(',')],
    queryFn: () => api.filmForMe(id, effectiveFilms(profile!)),
    enabled: profile != null,
    retry: false,
  })
  const ratings = new Map(profile?.films.map((f) => [f.tmdb_id, f.rating]))

  if (!profile) {
    return (
      <section className="panel" aria-labelledby="closest">
        <h2 id="closest">How it fits your taste</h2>
        <p className="m-0 text-muted">
          <Link to="/">Import your films</Link> to see which of the films you rated are closest to
          this one.
        </p>
      </section>
    )
  }
  if (q.isPending) return <Loading what="your closest films" />
  if (q.isError || !q.data.closest.length) return null
  const { seen, rating, match, closest } = q.data
  return (
    <section className="panel" aria-labelledby="closest">
      <div className="why-head">
        <h2 id="closest">Closest films you rated</h2>
        {match != null && !seen && <span className="label">Your match {match}%</span>}
      </div>
      {seen && (
        <p className="m-0 mb-3 text-muted">
          You have seen this one{rating != null && <> and rated it </>}
          {rating != null && <Stars rating={rating} />}. These are the others nearest to it.
        </p>
      )}
      <div className="row">
        {closest.map((c: ClosestFilm) => (
          <figure key={c.tmdb_id} className="fc m-0">
            <div className="pw">
              <PosterLink id={c.tmdb_id}>
                <Poster id={c.tmdb_id} title={c.title} path={c.poster_path} />
              </PosterLink>
            </div>
            <figcaption>
              <b>
                <FilmLink id={c.tmdb_id}>{c.title}</FilmLink>
              </b>
              <small>{c.year}</small>
              {ratings.get(c.tmdb_id) != null && <Stars rating={ratings.get(c.tmdb_id) as number} />}
              <small>{c.match}% similar</small>
            </figcaption>
          </figure>
        ))}
      </div>
    </section>
  )
}

function Header({ f }: { f: FilmDetail }) {
  return (
    <section className="hero" aria-labelledby="film-title">
      <div className="lb">
        <Backdrop path={f.backdrop_path} />
      </div>
      <div className="hero-body">
        <div className="pwrap">
          <Poster id={f.tmdb_id} title={f.title} path={f.poster_path} />
        </div>
        <div className="txt">
          <p className="eyebrow m-0">{f.franchise ?? 'Film'}</p>
          <h1 id="film-title">{f.title}</h1>
          {f.original_title && <p className="m-0 text-muted">{f.original_title}</p>}
          <p className="meta m-0">
            {f.year != null && (
              <span>
                <Link to={browsePath('era', decadeOf(f.year))} title={`More from the ${decadeOf(f.year)}s`}>
                  {f.year}
                </Link>
              </span>
            )}
            {runtimeLabel(f.runtime) && <span>{runtimeLabel(f.runtime)}</span>}
            {f.tmdb_rating != null && <span>TMDB {f.tmdb_rating.toFixed(1)}</span>}
          </p>
          {f.genres.length > 0 && (
            <div className="chips mt-3">
              {f.genres.map((g) => (
                <Link key={g} to={browsePath('genre', g)} className="chip">
                  {g}
                </Link>
              ))}
            </div>
          )}
          {f.tagline && <p className="m-0 mt-4 italic text-muted">{f.tagline}</p>}
          {f.overview && <p className="mt-3 max-w-[62ch]">{f.overview}</p>}
          {f.directors.length > 0 && (
            <p className="m-0 mt-3">
              <span className="label">Directed by </span>
              {f.directors.map((d, i) => (
                <span key={d}>
                  {i > 0 && ', '}
                  <Link to={browsePath('director', d)}>{d}</Link>
                </span>
              ))}
            </p>
          )}
          <div className="chips mt-4">
            <a className="btn primary" href={tmdbWatchUrl(f.tmdb_id)} target="_blank" rel="noreferrer">
              Where to watch
            </a>
            <a
              className="btn secondary"
              href={`https://www.themoviedb.org/movie/${f.tmdb_id}`}
              target="_blank"
              rel="noreferrer"
            >
              TMDB
            </a>
          </div>
          <p className="avail">
            <span className="label">Streaming (US)</span>
            {f.providers.length > 0 ? (
              f.providers.slice(0, 6).map((p) => (
                <span key={p} className="chip">
                  {p}
                </span>
              ))
            ) : (
              <span>Not on a subscription service we know of</span>
            )}
            <span>
              {f.providers_as_of ? `as of ${prettyDate(f.providers_as_of)} · ` : ''}via JustWatch
            </span>
          </p>
        </div>
      </div>
    </section>
  )
}

function Cast({ f }: { f: FilmDetail }) {
  if (f.cast.length === 0) return null
  return (
    <section className="panel" aria-labelledby="cast">
      <h2 id="cast">Cast</h2>
      <ul className="m-0 grid list-none gap-x-8 gap-y-2 p-0 sm:grid-cols-2">
        {f.cast.map((c, i) => (
          <li key={`${c.name}-${i}`}>
            <b>
              <Link to={browsePath('actor', c.name)}>{c.name}</Link>
            </b>
            {c.character && <span className="text-muted"> as {c.character}</span>}
          </li>
        ))}
      </ul>
    </section>
  )
}

function Similar({ id }: { id: number }) {
  const q = useQuery({ queryKey: ['similar', id], queryFn: () => api.similar(id) })
  if (q.isPending) return <Loading what="similar films" />
  if (q.isError || q.data.films.length === 0) return null
  return (
    <>
      <h2 className="sec">
        If you liked this, <em>try</em>
      </h2>
      <div className="row">
        {q.data.films.map((f) => (
          <SimilarCard key={f.media_key} f={f} />
        ))}
      </div>
    </>
  )
}

export function Film() {
  const id = parseFilmId(useParams().tmdbId)
  const q = useQuery({
    queryKey: ['film', id],
    queryFn: () => api.film(id as number),
    enabled: id != null,
    retry: (count, err) => !(err instanceof ApiError && err.status === 404) && count < 1,
  })

  const notFound = id == null || (q.error instanceof ApiError && q.error.status === 404)
  return (
    <Shell title={q.data?.title ?? 'Film'}>
      <div className="pt-6">
        {notFound && (
          <div className="mx-auto max-w-xl py-20 text-center">
            <p className="m-0 text-xl">We don't have that film in the catalog.</p>
            <p className="text-muted">
              <Link to="/">Back to PlotPoints</Link>
            </p>
          </div>
        )}
        {!notFound && q.isPending && <Loading what="this film" />}
        {!notFound && q.isError && <ErrorNote error={q.error} retry={() => q.refetch()} />}
        {q.data && (
          <>
            <Header f={q.data} />
            <Ad kind="leaderboard" />
            <ClosestToYou id={q.data.tmdb_id} />
            <Ad kind="infeed" />
            <Cast f={q.data} />
            <Similar id={q.data.tmdb_id} />
          </>
        )}
      </div>
    </Shell>
  )
}
