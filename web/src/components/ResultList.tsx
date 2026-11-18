import { joinList } from '../lib/format'
import type { Result } from '../lib/types'
import { Match, Tile } from './Tile'

const tmdbPage = (id: number) => `https://www.themoviedb.org/movie/${id}`

function because(r: Result): string[] {
  return (r.members[0]?.because ?? []).map((b) => b.title)
}

function Title({ r, className = '' }: { r: Result; className?: string }) {
  return (
    <h3 className={`m-0 font-bold ${className}`}>
      <a href={tmdbPage(r.tmdb_id)} target="_blank" rel="noreferrer" className="no-underline hover:underline">
        {r.title}
      </a>{' '}
      {r.year && <span className="font-normal text-muted">({r.year})</span>}
    </h3>
  )
}

/**
 * One list, three layouts, switched by CSS only so there is no flash on resize:
 *   phone   <640   compact rows
 *   tablet  640+   a card grid (the "hero and grid" layout)
 *   desktop 1024+  the ruled list
 * `overall` shows each pick's rank in the unfiltered list, used on the Streaming page.
 */
export function ResultList({ results, overall = false }: { results: Result[]; overall?: boolean }) {
  return (
    <>
      <div className="hidden lg:block">
        {results.map((r) => (
          <article
            key={r.media_key}
            className="rowp press -mx-5 flex flex-wrap items-center gap-x-8 gap-y-4 rounded-xl border-b border-line px-5 py-8"
          >
            <div className="w-[44px] flex-none text-[30px] font-bold leading-[1.1] tabular-nums text-muted">
              {r.rank}
              {overall && r.overall_rank != null && (
                <div className="mt-0.5 text-[13px] font-normal tracking-[0.02em]">
                  overall {r.overall_rank}
                </div>
              )}
            </div>
            <Tile
              id={r.tmdb_id}
              title={r.title}
              className="h-[108px] w-[72px] flex-none rounded-[9px] p-[9px] text-[12.5px]"
            />
            <div className="min-w-0 flex-[1_1_380px]">
              <Title r={r} className="mb-1 text-[28px] leading-[1.15]" />
              <div className="text-lg text-muted">Because you watched {joinList(because(r))}</div>
              {r.tmdb_rating != null && (
                <div className="mt-0.5 text-base text-muted">TMDB {r.tmdb_rating.toFixed(1)}</div>
              )}
            </div>
            <div className="w-[110px] flex-none">
              <div className="flex flex-col items-end">
                <span className="text-[46px] font-bold leading-none tabular-nums text-accent">
                  {r.match}%
                </span>
                <span className="mt-1 text-[13px] font-bold uppercase tracking-[0.14em] text-muted">
                  match
                </span>
              </div>
            </div>
          </article>
        ))}
      </div>

      <div className="hidden grid-cols-3 gap-6 sm:grid lg:hidden">
        {results.map((r) => (
          <article key={r.media_key} className="press flex min-w-0 flex-col gap-3 rounded-[14px] bg-surface p-3.5">
            <Tile
              id={r.tmdb_id}
              title={r.title}
              className="aspect-[2/3] rounded-[10px] p-3.5 text-[21px]"
            />
            <div className="min-w-0">
              <Title r={r} className="text-[19px] leading-[1.2]" />
              <div className="text-[15px] text-muted">
                {r.year}
                {r.tmdb_rating != null && ` · TMDB ${r.tmdb_rating.toFixed(1)}`}
                {overall && r.overall_rank != null && ` · overall ${r.overall_rank}`}
              </div>
            </div>
            <div className="text-[15px] leading-[1.4] text-muted">Because: {joinList(because(r))}</div>
            <div className="mt-auto">
              <Match value={r.match} size="text-[34px]" />
            </div>
          </article>
        ))}
      </div>

      <div className="sm:hidden">
        {results.map((r) => (
          <article key={r.media_key} className="press flex items-center gap-3 border-b border-line py-5">
            <div className="w-6 flex-none text-xl font-bold tabular-nums text-muted">{r.rank}</div>
            <Tile
              id={r.tmdb_id}
              title={r.title}
              className="h-[84px] w-14 flex-none rounded-[7px] p-1.5 text-[10.5px]"
            />
            <div className="min-w-0 flex-1">
              <Title r={r} className="text-lg leading-[1.15]" />
              <div className="mt-0.5 text-sm leading-[1.35] text-muted">
                Because {joinList(because(r))}
                {overall && r.overall_rank != null && ` · overall ${r.overall_rank}`}
              </div>
            </div>
            <div className="flex-none text-right text-[30px] font-bold leading-none tabular-nums text-accent">
              {r.match}%
            </div>
          </article>
        ))}
      </div>
    </>
  )
}
