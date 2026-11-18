import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Navigate } from 'react-router-dom'
import { ResultList } from '../components/ResultList'
import { Shell } from '../components/Shell'
import { ErrorNote, Loading, PageTitle } from '../components/States'
import { api } from '../lib/api'
import { joinList, prettyDate } from '../lib/format'
import { useProfile, type Profile } from '../lib/profile'
import { useRecommendations } from './ForYou'

const KEY = 'pp-services'
const SHOWN = 24 // the most widely available services; the long tail is mostly Amazon channels

function readServices(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? '[]')
    return Array.isArray(v) ? v.filter((x) => typeof x === 'string') : []
  } catch {
    return []
  }
}

export function Streaming() {
  const { profile } = useProfile()
  if (!profile) return <Navigate to="/" replace />
  return <StreamingFor profile={profile} />
}

function StreamingFor({ profile }: { profile: Profile }) {
  const meta = useQuery({ queryKey: ['meta'], queryFn: api.meta, staleTime: Infinity })
  const [chosen, setChosen] = useState<string[]>(readServices)
  const q = useRecommendations(profile, chosen, chosen.length > 0, 10)
  const results = q.data?.pages.flatMap((p) => p.results) ?? []
  const first = q.data?.pages[0]

  const toggle = (name: string) => {
    const next = chosen.includes(name) ? chosen.filter((c) => c !== name) : [...chosen, name]
    setChosen(next)
    try {
      localStorage.setItem(KEY, JSON.stringify(next))
    } catch {
      /* the selection just will not persist */
    }
  }

  return (
    <Shell>
      <PageTitle title="What you can watch tonight">
        Choose the services you pay for. We rank only what is on them, so your top pick is always
        something you can press play on.
      </PageTitle>

      <section className="pb-4 pt-8 lg:pt-10">
        {meta.isPending && <Loading what="services" />}
        {meta.isError && <ErrorNote error={meta.error} retry={() => meta.refetch()} />}
        {meta.data && (
          <div role="group" aria-label="Your streaming services" className="flex flex-wrap gap-3">
            {meta.data.providers.slice(0, SHOWN).map((p) => {
              const on = chosen.includes(p.name)
              return (
                <button
                  key={p.name}
                  type="button"
                  aria-pressed={on}
                  onClick={() => toggle(p.name)}
                  className={`press min-h-[52px] cursor-pointer rounded-[10px] border-0 px-6 py-3 text-lg font-bold ${
                    on ? 'bg-accent text-on' : 'bg-surface2 text-ink'
                  }`}
                >
                  {p.name}
                </button>
              )
            })}
          </div>
        )}
      </section>

      <section className="pt-7">
        {chosen.length === 0 && (
          <p className="border-t border-line py-14 text-center text-xl text-muted">
            Pick a service above to see your best matches on it.
          </p>
        )}
        {chosen.length > 0 && (
          <>
            <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2 border-t border-line pt-9">
              <h2 className="m-0 text-[28px] font-bold tracking-[-0.01em] sm:text-4xl lg:text-[42px]">
                On {joinList(chosen)}
              </h2>
              {first?.pool_matches != null && (
                <span className="text-base text-muted lg:text-[17px]">
                  {first.pool_matches} of your top {first.pool_size} matches stream here. These are
                  the best of them.
                </span>
              )}
            </div>
            {q.isPending && <Loading />}
            {q.isError && <ErrorNote error={q.error} retry={() => q.refetch()} />}
            {q.data && results.length === 0 && (
              <p className="py-14 text-center text-xl text-muted">
                Nothing in your matches streams there right now.
              </p>
            )}
            <ResultList results={results} overall />
            {q.hasNextPage && (
              <div className="flex justify-center pt-11">
                <button
                  type="button"
                  disabled={q.isFetchingNextPage}
                  onClick={() => q.fetchNextPage()}
                  className="press min-h-[52px] w-full cursor-pointer rounded-xl border-0 bg-surface2 px-9 py-3.5 text-lg font-bold text-ink sm:w-auto lg:min-h-14 lg:text-[19px]"
                >
                  {q.isFetchingNextPage ? 'Loading…' : 'Show more'}
                </button>
              </div>
            )}
          </>
        )}
        {meta.data && (
          <div className="pt-7 text-center text-[15px] text-muted">
            Streaming data from JustWatch · United States only · availability as of{' '}
            {prettyDate(meta.data.providers_as_of)}
          </div>
        )}
      </section>
    </Shell>
  )
}
