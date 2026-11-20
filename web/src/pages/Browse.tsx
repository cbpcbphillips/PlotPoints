import { useQuery } from '@tanstack/react-query'
import { Link, Navigate } from 'react-router-dom'
import { PeopleSearch } from '../components/PeopleSearch'
import { Ad, Shell } from '../components/Shell'
import { PageTitle } from '../components/States'
import { api } from '../lib/api'
import { browsePath } from '../lib/browse'
import { useProfile } from '../lib/profile'

/** `/browse` : pick a genre or decade, or look up a director or actor. */
export function Browse() {
  const { profile } = useProfile()
  const facets = useQuery({ queryKey: ['facets'], queryFn: api.facets, staleTime: Infinity })
  if (!profile) return <Navigate to="/" replace />
  return (
    <Shell title="Browse">
      <PageTitle title="Browse">
        Pick a way in. Every list is still ranked by how close its films are to your taste, and it
        only shows films you have not seen.
      </PageTitle>
      <Ad kind="leaderboard" />

      <section aria-labelledby="by-genre" className="panel mt-4">
        <h2 id="by-genre" className="m-0 text-lg font-bold">
          Genres
        </h2>
        <div className="chips mt-3">
          {facets.data?.genres.map((g) => (
            <Link key={g.name} to={browsePath('genre', g.name)} className="chip">
              {g.name} <small className="text-muted">{g.count.toLocaleString()}</small>
            </Link>
          ))}
          {facets.isPending && <span className="text-muted">Loading…</span>}
          {facets.isError && <span role="alert">Could not load the genres.</span>}
        </div>
      </section>

      <section aria-labelledby="by-era" className="panel mt-4">
        <h2 id="by-era" className="m-0 text-lg font-bold">
          Decades
        </h2>
        <div className="chips mt-3">
          {facets.data?.decades.map((d) => (
            <Link key={d.decade} to={browsePath('era', d.decade)} className="chip">
              {d.decade}s <small className="text-muted">{d.count.toLocaleString()}</small>
            </Link>
          ))}
        </div>
      </section>

      <PeopleSearch kind="keyword" label="Themes" hrefFor={(n) => browsePath('keyword', n)} />
      <PeopleSearch kind="director" label="Directors" hrefFor={(n) => browsePath('director', n)} />
      <PeopleSearch kind="actor" label="Actors" hrefFor={(n) => browsePath('actor', n)} />
      <Ad kind="infeed" />
    </Shell>
  )
}
