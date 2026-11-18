import { useQuery } from '@tanstack/react-query'
import { Navigate } from 'react-router-dom'
import { Shell } from '../components/Shell'
import { ErrorNote, Loading, PageTitle } from '../components/States'
import { Match, Tile } from '../components/Tile'
import { api } from '../lib/api'
import { effectiveFilms, useProfile, type Profile } from '../lib/profile'

export function Franchises() {
  const { profile } = useProfile()
  if (!profile) return <Navigate to="/" replace />
  return <FranchisesFor profile={profile} />
}

function FranchisesFor({ profile }: { profile: Profile }) {
  const q = useQuery({
    queryKey: ['franchises', profile.importedAt, profile.matched, profile.notForMe.join(',')],
    queryFn: () =>
      api.franchises({ members: [{ name: profile.name, films: effectiveFilms(profile) }] }),
  })

  return (
    <Shell>
      <PageTitle title="Franchises">
        Your best match in each series comes first. Everything else in that franchise is one click
        away, so you can start anywhere.
      </PageTitle>
      {q.isPending && <Loading what="your franchises" />}
      {q.isError && <ErrorNote error={q.error} retry={() => q.refetch()} />}
      {q.data && (
        <section className="pt-6 lg:pt-9">
          {q.data.franchises.map((f) => (
            <article
              key={f.franchise}
              className="rowp press -mx-5 flex flex-wrap items-center gap-x-10 gap-y-6 rounded-xl border-t border-line px-5 py-8 lg:py-11"
            >
              <div className="min-w-0 flex-[1_1_100%] lg:flex-[0_0_230px]">
                <h2 className="m-0 text-[28px] font-bold leading-[1.05] tracking-[-0.01em] lg:text-4xl">
                  {f.franchise}
                </h2>
                <div className="mt-1.5 text-[17px] text-muted">{f.count} in your matches</div>
              </div>
              <Tile
                id={f.best.tmdb_id}
                title={f.best.title}
                className="h-[126px] w-[84px] flex-none rounded-[10px] p-2.5 text-[13.5px]"
              />
              <div className="flex min-w-0 flex-[1_1_240px] flex-col gap-1.5">
                <div className="text-sm font-bold uppercase tracking-[0.16em] text-accent">
                  Best match
                </div>
                <h3 className="m-0 text-2xl font-bold leading-[1.12] lg:text-[28px]">
                  {f.best.title}
                </h3>
                <div className="text-[17px] text-muted">
                  {f.best.year}
                  {f.best.tmdb_rating != null && ` · TMDB ${f.best.tmdb_rating.toFixed(1)}`}
                </div>
                <div className="pt-1.5">
                  <Match value={f.best.match} />
                </div>
              </div>
              <div className="flex min-w-0 flex-[1_1_300px] flex-col gap-3">
                <div className="text-sm font-bold uppercase tracking-[0.16em] text-muted">
                  Also in this franchise
                </div>
                <div className="flex flex-wrap gap-2.5">
                  {f.others.map((o) => (
                    <span
                      key={o.media_key}
                      className="rounded-lg bg-surface2 px-4 py-2 text-[17px] text-ink"
                    >
                      {o.title}
                    </span>
                  ))}
                </div>
              </div>
            </article>
          ))}
          {q.data.franchises.length === 0 && (
            <p className="py-10 text-center text-lg text-muted">
              None of your top matches belong to a franchise yet.
            </p>
          )}
          <div className="border-t border-line pt-7 text-center text-[17px] text-muted">
            Only franchises with two or more films in your matches are grouped.
          </div>
        </section>
      )}
    </Shell>
  )
}
