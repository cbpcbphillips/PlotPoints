import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'

/**
 * A search box over directors or billed actors, with the biggest names showing before you type.
 * `hrefFor` decides where a name leads, so the same box serves the Browse page (open that person)
 * and a filtered list (add that person as a filter).
 */
export function PeopleSearch({
  kind,
  label,
  hrefFor,
  headingLevel = 2,
  className = 'panel mt-4',
}: {
  kind: 'director' | 'actor'
  label: string
  hrefFor: (name: string) => string
  headingLevel?: 2 | 3
  className?: string
}) {
  const [text, setText] = useState('')
  const [q, setQ] = useState('')
  useEffect(() => {
    const t = window.setTimeout(() => setQ(text.trim()), 250)
    return () => window.clearTimeout(t)
  }, [text])
  const people = useQuery({
    queryKey: ['people', kind, q],
    queryFn: () => api.people(kind, q, 18),
    staleTime: 5 * 60_000,
    placeholderData: (prev) => prev,
  })
  const id = `find-${kind}`
  const Heading = headingLevel === 2 ? 'h2' : 'h3'
  return (
    <section aria-labelledby={`${id}-h`} className={className}>
      <Heading id={`${id}-h`} className="m-0 text-lg font-bold">
        {label}
      </Heading>
      <label htmlFor={id} className="mt-2 block text-sm text-muted">
        Search by name
      </label>
      <input
        id={id}
        type="search"
        value={text}
        onChange={(e) => setText(e.target.value)}
        autoComplete="off"
        spellCheck={false}
        className="mt-1 min-h-11 w-full max-w-md rounded-[10px] border-[1.5px] border-field bg-bg px-4 text-base text-ink"
      />
      <p className="m-0 mt-3 text-sm text-muted" role="status">
        {q ? `Matches for "${q}"` : 'Most films in the catalog'}
        {people.isFetching ? '…' : ''}
      </p>
      <div className="chips mt-2">
        {people.data?.people.map((p) => (
          <Link key={p.name} to={hrefFor(p.name)} className="chip">
            {p.name} <small className="text-muted">{p.count}</small>
          </Link>
        ))}
        {people.data && people.data.people.length === 0 && (
          <span className="text-muted">Nobody by that name.</span>
        )}
      </div>
    </section>
  )
}
