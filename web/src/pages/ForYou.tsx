import { useInfiniteQuery } from '@tanstack/react-query'
import { Navigate } from 'react-router-dom'
import { ResultList } from '../components/ResultList'
import { Shell } from '../components/Shell'
import { ErrorNote, Loading } from '../components/States'
import { Match, Tile } from '../components/Tile'
import { api } from '../lib/api'
import { joinList, ratedPhrase, tmdbWatchUrl } from '../lib/format'
import { effectiveFilms, useProfile, type Profile } from '../lib/profile'
import type { Result } from '../lib/types'

const FIRST_PAGE = 11 // the top match, plus ten more
const PAGE = 10

/**
 * Recommendations for the current profile, paged. Shared with the Streaming page, which has no
 * hero and so passes firstPage = PAGE.
 */
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
      }),
    getNextPageParam: (last, pages) =>
      last.has_more ? pages.reduce((n, p) => n + p.results.length, 0) : undefined,
  })
}

function Hero({ r, profile, onNope }: { r: Result; profile: Profile; onNope: () => void }) {
  const because = r.members[0]?.because ?? []
  const ratings = new Map(profile.films.map((f) => [f.tmdb_id, f.rating]))
  const meta = [r.year, r.genres.slice(0, 3).join(', '), r.tmdb_rating && `TMDB ${r.tmdb_rating.toFixed(1)}`]
    .filter(Boolean)
    .join(' · ')

  const buttons = (
    <div className="flex flex-col gap-2.5 pt-1 sm:flex-row sm:flex-wrap sm:gap-2.5 lg:gap-3 lg:pt-1.5">
      <a
        href={tmdbWatchUrl(r.tmdb_id)}
        target="_blank"
        rel="noreferrer"
        className="press inline-flex min-h-[52px] items-center justify-center rounded-xl bg-accent px-7 py-3.5 text-lg font-bold text-on no-underline sm:px-7 lg:min-h-14 lg:px-8 lg:text-[19px]"
      >
        Where to watch
      </a>
      <button
        type="button"
        onClick={onNope}
        className="press min-h-[52px] cursor-pointer rounded-xl border-0 bg-surface2 px-7 py-3.5 text-lg font-bold text-ink lg:min-h-14 lg:px-8 lg:text-[19px]"
      >
        Not for me
      </button>
    </div>
  )

  return (
    <section aria-labelledby="top-match" className="pb-10 pt-6 sm:pb-16 sm:pt-14 lg:pb-24 lg:pt-20">
      {/* phone: a card, small tile beside the title */}
      <div className="flex flex-col gap-4 rounded-2xl bg-surface p-[18px] sm:hidden">
        <div className="text-[13px] font-bold uppercase tracking-[0.16em] text-accent">
          Tonight&rsquo;s top match
        </div>
        <div className="flex items-start gap-4">
          <Tile
            id={r.tmdb_id}
            title={r.title}
            className="h-[162px] w-[108px] flex-none rounded-[10px] p-2.5 text-[15px]"
          />
          <div className="flex min-w-0 flex-1 flex-col gap-1.5">
            <h1 className="m-0 text-2xl font-bold leading-[1.08] tracking-[-0.01em]">{r.title}</h1>
            <div className="text-[15px] text-muted">{meta}</div>
            <div className="mt-1">
              <Match value={r.match} size="text-[44px]" />
            </div>
          </div>
        </div>
        <div className="text-[15px] text-muted">
          Because you watched {joinList(because.map((b) => b.title))}
        </div>
        {buttons}
      </div>

      {/* tablet and desktop */}
      <div className="hidden gap-9 sm:flex sm:flex-wrap sm:items-center lg:flex-nowrap lg:items-start lg:gap-14">
        <Tile
          id={r.tmdb_id}
          title={r.title}
          className="aspect-[2/3] w-[250px] flex-none rounded-[14px] p-[22px] text-[32px] lg:order-2 lg:w-[360px] lg:p-7 lg:text-[40px]"
        />
        <div className="flex min-w-0 flex-[1_1_340px] flex-col items-start gap-[18px] lg:order-1 lg:gap-[26px]">
          <div
            id="top-match"
            className="text-sm font-bold uppercase tracking-[0.16em] text-accent lg:text-[15px]"
          >
            Tonight&rsquo;s top match
          </div>
          <h1 className="m-0 text-balance text-[46px] font-bold leading-none tracking-[-0.02em] lg:text-[72px]">
            {r.title}
          </h1>
          <p className="m-0 hidden max-w-[30em] text-2xl italic leading-[1.45] text-muted lg:block">
            Closest to {joinList(because.map((b) => b.title))}, which you rated highly. This is the
            best film you have not seen.
          </p>
          <div className="text-[17px] text-muted lg:text-lg">{meta}</div>
          <Match value={r.match} size="text-[60px] lg:text-[76px]" />
          <div className="text-[17px] text-muted lg:hidden">
            Because you watched {joinList(because.map((b) => b.title))}
          </div>
          {buttons}
          <aside className="hidden w-full max-w-[420px] flex-col gap-1.5 rounded-[14px] bg-surface p-7 lg:flex">
            <div className="mb-2 text-[15px] font-bold uppercase tracking-[0.14em] text-muted">
              Closest films you have seen
            </div>
            {because.map((b) => (
              <div key={b.tmdb_id} className="flex justify-between gap-3.5 py-2">
                <span className="text-[19px]">{b.title}</span>
                <span className="whitespace-nowrap font-bold text-accent">
                  {ratedPhrase(ratings.get(b.tmdb_id) ?? null)}
                </span>
              </div>
            ))}
          </aside>
        </div>
      </div>
    </section>
  )
}

export function ForYou() {
  const { profile, markNotForMe } = useProfile()
  if (!profile) return <Navigate to="/" replace />
  return <ForYouFor profile={profile} onNope={markNotForMe} />
}

function ForYouFor({ profile, onNope }: { profile: Profile; onNope: (id: number) => void }) {
  const q = useRecommendations(profile)
  const results = q.data?.pages.flatMap((p) => p.results) ?? []
  const [top, ...rest] = results

  return (
    <Shell>
      {q.isPending && <Loading />}
      {q.isError && <ErrorNote error={q.error} retry={() => q.refetch()} />}
      {top && (
        <>
          <Hero r={top} profile={profile} onNope={() => onNope(top.tmdb_id)} />
          <section>
            <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2 border-t border-line pt-6 sm:mb-7 sm:pt-8 lg:mb-3 lg:pt-10">
              <h2 className="m-0 text-[28px] font-bold tracking-[-0.01em] sm:text-4xl lg:text-[42px]">
                <span className="sm:hidden">Your list</span>
                <span className="hidden sm:inline lg:hidden">More for you</span>
                <span className="hidden lg:inline">The rest of your list</span>
              </h2>
              <span className="text-sm text-muted sm:text-base lg:text-[17px]">
                Closest to what you rated highly
              </span>
            </div>
            <ResultList results={rest} />
            {q.hasNextPage && (
              <div className="flex justify-center pt-8 lg:pt-12">
                <button
                  type="button"
                  disabled={q.isFetchingNextPage}
                  onClick={() => q.fetchNextPage()}
                  className="press min-h-[52px] w-full cursor-pointer rounded-xl border-0 bg-surface2 px-9 py-3.5 text-lg font-bold text-ink sm:w-auto lg:min-h-14 lg:text-[19px]"
                >
                  {q.isFetchingNextPage ? 'Loading…' : 'Show 10 more'}
                </button>
              </div>
            )}
            {q.data?.pages[0].unmatched_films ? (
              <p className="pt-8 text-center text-[15px] text-muted">
                {q.data.pages[0].unmatched_films} of your films are not in the catalog, so they
                could not be used.
              </p>
            ) : null}
          </section>
        </>
      )}
    </Shell>
  )
}
