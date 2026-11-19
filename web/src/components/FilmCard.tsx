import type { Result } from '../lib/types'
import { Poster } from './Poster'
import { SignalRow } from './Signals'

/** One recommendation in a reel: poster, title, year and rank, the score, then the three signals. */
export function FilmCard({ r }: { r: Result }) {
  return (
    <figure className="fc m-0">
      <div className="pw">
        <Poster id={r.tmdb_id} title={r.title} path={r.poster_path} />
      </div>
      <figcaption>
        <b>
          <a
            href={`https://www.themoviedb.org/movie/${r.tmdb_id}`}
            target="_blank"
            rel="noreferrer"
            className="no-underline hover:underline"
          >
            {r.title}
          </a>
        </b>
        <small>
          {r.year} · #{r.rank} overall
        </small>
        <div className="sc">
          <b>{r.score.toFixed(1)}</b>
          <span>score</span>
        </div>
        <SignalRow r={r} />
      </figcaption>
    </figure>
  )
}
