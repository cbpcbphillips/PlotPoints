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

/**
 * The same link wrapped around a poster. Mouse and touch users can click the poster; keyboard and
 * screen-reader users get one stop per card, the title link, so it is out of the tab order and
 * hidden from assistive tech (it only repeats the title link).
 */
export function PosterLink({ id, children }: { id: number; children: ReactNode }) {
  return (
    <Link to={filmPath(id)} tabIndex={-1} aria-hidden="true" className="block text-inherit">
      {children}
    </Link>
  )
}
