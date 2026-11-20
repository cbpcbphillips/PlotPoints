import { Link } from 'react-router-dom'
import type { Result } from '../lib/types'
import { FilmLink } from './FilmLink'
import { Poster } from './Poster'
import { SignalRow } from './Signals'

/** One recommendation in a reel: poster, title, year and rank, the score, then the three signals. */
export function FilmCard({ r }: { r: Result }) {
  return (
    <figure className="fc m-0">
      <div className="pw">
        <FilmLink id={r.tmdb_id} label={`${r.title} details`}>
          <Poster id={r.tmdb_id} title={r.title} path={r.poster_path} />
        </FilmLink>
      </div>
      <figcaption>
        <b>
          <FilmLink id={r.tmdb_id}>{r.title}</FilmLink>
        </b>
        <small>
          {r.year} · #{r.rank} overall
        </small>
        {r.bundle && (
          <small>
            <Link to="/franchises" className="text-inherit hover:underline">
              +{r.bundle.more} more {r.bundle.franchise}
            </Link>
          </small>
        )}
        <div className="sc">
          <b>{r.score.toFixed(1)}</b>
          <span>score</span>
        </div>
        <SignalRow r={r} />
      </figcaption>
    </figure>
  )
}
