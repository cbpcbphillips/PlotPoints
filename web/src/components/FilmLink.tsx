import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { filmPath } from '../lib/format'

/** A link to a film's own page. Plain text styling: the surrounding title style carries through. */
export function FilmLink({
  id,
  label,
  children,
}: {
  id: number
  label?: string
  children: ReactNode
}) {
  return (
    <Link to={filmPath(id)} aria-label={label} className="text-inherit no-underline hover:underline">
      {children}
    </Link>
  )
}
