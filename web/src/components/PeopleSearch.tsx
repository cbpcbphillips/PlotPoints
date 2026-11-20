import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'

/**
 * A search box over directors, billed actors or themes, with the biggest showing before you type.
 * `hrefFor` decides where a name leads, so the same box serves the Browse page (open that one)
 * and a filtered list (add or take off that filter); `isSelected` marks the ones already on.
 */
export function PeopleSearch({
  kind,
  label,
  hrefFor,
  isSelected,
  headingLevel = 2,
  className = 'panel mt-4',
}: {
  kind: 'director' | 'actor' | 'keyword'
  label: string
  hrefFor: (name: string) => string
  isSelected?: (name: string) => boolean
  headingLevel?: 2 | 3
  className?: string
}) {
  const [text, setText] = useState('')
  const [q, setQ] = useState('')
  useEffect(() => {
    const t = window.setTimeout(() => setQ(text.trim()), 250)
    return () => window.clearTimeout(t)
  }, [text])
  const names = useQuery({
    queryKey: ['names', kind, q],
    queryFn: async () =>
      kind === 'keyword'
        ? (await api.keywords(q, 18)).keywords
        : (await api.people(kind, q, 18)).people,
    staleTime: 5 * 60_000,
    placeholderData: (prev) => prev,
  })
  const id = `find-${kind}`
  const Heading = headingLevel === 2 ? 'h2' : 'h3'
  const none = kind === 'keyword' ? 'No theme like that.' : 'Nobody by that name.'
  const idle = kind === 'keyword' ? 'Most common themes' : 'Most films in the catalog'
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
        {q ? `Matches for "${q}"` : idle}
        {names.isFetching ? '…' : ''}
      </p>
      <div className="chips mt-2">
        {names.data?.map((p) => (
          <Link
            key={p.name}
            to={hrefFor(p.name)}
            className={`chip${isSelected?.(p.name) ? ' sel' : ''}`}
            aria-current={isSelected?.(p.name) ? 'true' : undefined}
          >
            {p.name} <small className="text-muted">{p.count}</small>
          </Link>
        ))}
        {names.data && names.data.length === 0 && <span className="text-muted">{none}</span>}
      </div>
    </section>
  )
}
