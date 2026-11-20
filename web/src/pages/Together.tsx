import { useInfiniteQuery } from '@tanstack/react-query'
import { useRef, useState, type FormEvent } from 'react'
import { Navigate } from 'react-router-dom'
import { FilmLink, PosterLink } from '../components/FilmLink'
import { Poster } from '../components/Poster'
import { Ad, Shell } from '../components/Shell'
import { ErrorNote, Loading, PageTitle } from '../components/States'
import { api } from '../lib/api'
import { combineExport, readExportFiles } from '../lib/export'
import { tmdbWatchUrl } from '../lib/format'
import { MAX_NAME, MAX_OTHERS, uniqueName, useGroup, type GroupMember } from '../lib/group'
import { fromFeed, fromMatch } from '../lib/importing'
import { effectiveFilms, useProfile, type Profile } from '../lib/profile'
import type { Film, Result } from '../lib/types'

const FIRST_PAGE = 20
const PAGE = 10
const FEW_LIKED = 10 // the thinnest member below this: say so

interface Person {
  name: string
  films: Film[]
}

function useGroupRecommendations(people: Person[], enabled: boolean) {
  const key = people.map((p) => `${p.name}:${p.films.length}`).join('|')
  return useInfiniteQuery({
    queryKey: ['group', key],
    enabled,
    initialPageParam: 0,
    retry: false, // a person with nothing rated is a 422 that will not fix itself
    queryFn: ({ pageParam }) =>
      api.recommend({
        members: people,
        offset: pageParam,
        limit: pageParam === 0 ? FIRST_PAGE : PAGE,
        bundle: true,
      }),
    getNextPageParam: (last, pages) =>
      last.has_more ? pages.reduce((n, p) => n + p.results.length, 0) : undefined,
  })
}

/** Add one person, from a Letterboxd export or a username. Their films stay in this browser. */
function AddPerson({ taken, onAdd }: { taken: string[]; onAdd: (m: GroupMember) => void }) {
  const fileInput = useRef<HTMLInputElement>(null)
  const [label, setLabel] = useState('')
  const [username, setUsername] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    const handle = username.trim()
    if (!files.length && !handle) {
      setError('Choose their Letterboxd export, or type their username.')
      return
    }
    setBusy(true)
    try {
      const fromExport = files.length > 0
      const outcome = fromExport
        ? fromMatch(await api.match(combineExport(await readExportFiles(files))))
        : fromFeed((await api.importLetterboxd(handle)).films)
      if (!outcome.films.length) throw new Error('No films found in that import.')
      onAdd({
        name: uniqueName(label || handle, taken),
        films: outcome.films,
        source: fromExport ? 'export' : 'username',
        addedAt: new Date().toISOString(),
      })
      setLabel('')
      setUsername('')
      setFiles([])
      if (fileInput.current) fileInput.current.value = ''
    } catch (err) {
      setError(err instanceof Error ? err.message : 'That import failed. Try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} noValidate className="mt-4 grid gap-4 sm:max-w-xl">
      <div className="grid gap-1.5">
        <label htmlFor="g-name" className="font-bold">
          Their name <span className="font-normal text-muted">(optional)</span>
        </label>
        <input
          id="g-name"
          value={label}
          maxLength={MAX_NAME - 4}
          onChange={(e) => setLabel(e.target.value)}
          autoComplete="off"
          className="min-h-11 rounded-[10px] border-[1.5px] border-field bg-bg px-4 text-base text-ink"
        />
      </div>
      <div className="grid gap-1.5">
        <label htmlFor="g-user" className="font-bold">
          Letterboxd username
        </label>
        <input
          id="g-user"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          aria-describedby="g-hint"
          className="min-h-11 rounded-[10px] border-[1.5px] border-field bg-bg px-4 text-base text-ink"
        />
        <p id="g-hint" className="m-0 text-sm text-muted">
          A username only brings in their latest 50 or so entries. Their export loads their full
          history.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <input
          ref={fileInput}
          type="file"
          accept=".zip,.csv"
          multiple
          className="sr-only"
          tabIndex={-1}
          aria-hidden="true"
          onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
        />
        <button type="button" className="btn secondary" onClick={() => fileInput.current?.click()}>
          Or choose their export file
        </button>
        {files.length > 0 && <span className="text-sm">{files.map((f) => f.name).join(', ')}</span>}
      </div>
      {error && (
        <p role="alert" className="m-0 rounded-[10px] border border-field px-4 py-3">
          {error}
        </p>
      )}
      <div>
        <button type="submit" className="btn primary lg" disabled={busy}>
          {busy ? 'Reading their history…' : 'Add to the group'}
        </button>
      </div>
    </form>
  )
}

/** One film, and how well each person in the group would take to it. */
function GroupRow({ r }: { r: Result }) {
  return (
    <li className="panel grid grid-cols-[92px_1fr] gap-4 sm:grid-cols-[110px_1fr]">
      <PosterLink id={r.tmdb_id}>
        <Poster id={r.tmdb_id} title={r.title} path={r.poster_path} />
      </PosterLink>
      <div className="min-w-0">
        {r.picked_for && <p className="eyebrow m-0">{r.picked_for}&rsquo;s pick</p>}
        <h3 className="m-0 font-title text-xl font-bold">
          <FilmLink id={r.tmdb_id}>{r.title}</FilmLink>
        </h3>
        <p className="m-0 text-sm text-muted">
          {[r.year, r.runtime && `${r.runtime} min`, r.genres.slice(0, 2).join(', ')]
            .filter(Boolean)
            .join(' · ')}
        </p>
        <ul
          className="m-0 mt-3 grid list-none gap-1.5 p-0"
          aria-label="How well it fits each person"
        >
          {(r.fit ?? []).map((f) => (
            <li
              key={f.member}
              className="grid grid-cols-[minmax(4rem,9rem)_1fr_5.5rem] items-center gap-3"
            >
              <span className="truncate text-sm">{f.member}</span>
              <span className="h-2 rounded-full bg-surface2" aria-hidden="true">
                <span
                  className="block h-2 rounded-full bg-accent"
                  style={{ width: `${Math.max(8, 100 - (f.top_percent - 1) * 2.5)}%` }}
                />
              </span>
              <span className="text-right text-sm font-bold tabular-nums">
                top {f.top_percent}%
              </span>
            </li>
          ))}
        </ul>
        <p className="m-0 mt-3 flex flex-wrap items-center gap-2 text-sm">
          {r.providers.slice(0, 3).map((p) => (
            <span key={p} className="chip">
              {p}
            </span>
          ))}
          <a href={tmdbWatchUrl(r.tmdb_id)} target="_blank" rel="noreferrer">
            Where to watch
          </a>
        </p>
      </div>
    </li>
  )
}

/** `/together` : one list for everyone in the room, built by taking turns. */
export function Together() {
  const { profile } = useProfile()
  if (!profile) return <Navigate to="/" replace />
  return <TogetherFor profile={profile} />
}

function TogetherFor({ profile }: { profile: Profile }) {
  const { members, add, remove, clear } = useGroup()
  const me: Person = { name: profile.name, films: effectiveFilms(profile) }
  const others = members.filter((m) => m.name.toLowerCase() !== me.name.toLowerCase())
  const people = [me, ...others.map((m) => ({ name: m.name, films: m.films }))]
  const ready = others.length > 0
  const q = useGroupRecommendations(people, ready)
  const results = q.data?.pages.flatMap((p) => p.results) ?? []
  const thinnest = q.data?.pages[0].liked_films

  return (
    <Shell title="Watch together">
      <PageTitle title="Watch together">
        Add the people you are watching with. You take turns: each pick is a film one person would
        love that everyone else can live with, so nobody gets dragged along.
      </PageTitle>
      <Ad kind="leaderboard" />

      <section className="panel mt-4" aria-labelledby="who">
        <h2 id="who" className="m-0 text-lg font-bold">
          Who is watching
        </h2>
        <ul className="m-0 mt-3 grid list-none gap-2 p-0">
          <li className="flex flex-wrap items-center gap-3">
            <b>{me.name}</b>
            <span className="text-sm text-muted">
              you · {profile.matched.toLocaleString()} films
            </span>
          </li>
          {others.map((m) => (
            <li key={m.name} className="flex flex-wrap items-center gap-3">
              <b>{m.name}</b>
              <span className="text-sm text-muted">
                {m.films.length.toLocaleString()} films ·{' '}
                {m.source === 'export' ? 'export' : 'latest entries'}
              </span>
              <button
                type="button"
                className="btn ghost"
                aria-label={`Remove ${m.name} from the group`}
                onClick={() => remove(m.name)}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
        {others.length > 0 && (
          <p className="m-0 mt-3">
            <button type="button" className="btn ghost" onClick={clear}>
              Clear everyone but me
            </button>
          </p>
        )}
        {others.length < MAX_OTHERS ? (
          <>
            <h3 className="m-0 mt-6 text-base font-bold">Add someone</h3>
            <AddPerson taken={[me.name, ...others.map((m) => m.name)]} onAdd={add} />
          </>
        ) : (
          <p className="m-0 mt-4 text-muted">
            That is the most a group can hold ({MAX_OTHERS + 1}).
          </p>
        )}
      </section>

      {!ready && <p className="empty mt-4">Add one more person to see what you could all watch.</p>}
      {ready && q.isPending && <Loading what="films for everyone" />}
      {ready && q.isError && <ErrorNote error={q.error} retry={() => q.refetch()} />}
      {thinnest != null && thinnest < FEW_LIKED && (
        <p
          role="status"
          className="mt-4 rounded-lg border border-line border-l-4 border-l-accent bg-surface px-4 py-3 text-sm"
        >
          The thinnest history in the group has only {thinnest} {thinnest === 1 ? 'film' : 'films'}{' '}
          rated above 3 stars, so this list leans on very little for that person. An export gives a
          better picture than a username (a username only brings in the latest 50 or so entries).
        </p>
      )}
      {results.length > 0 && (
        <>
          <h2 className="sec">
            Films you could <em>all</em> watch
          </h2>
          <p className="m-0 mb-3 max-w-[62ch] text-sm text-muted">
            &ldquo;Top 3%&rdquo; means the film is in that person&rsquo;s best 3% of everything we
            could suggest to them.
          </p>
          <ol className="m-0 grid list-none gap-4 p-0">
            {results.map((r) => (
              <GroupRow key={r.media_key} r={r} />
            ))}
          </ol>
          {q.hasNextPage && (
            <div className="flex justify-center pt-6">
              <button
                type="button"
                className="btn secondary lg"
                disabled={q.isFetchingNextPage}
                onClick={() => q.fetchNextPage()}
              >
                {q.isFetchingNextPage ? 'Loading…' : 'Show 10 more'}
              </button>
            </div>
          )}
        </>
      )}
      <Ad kind="infeed" />
    </Shell>
  )
}
