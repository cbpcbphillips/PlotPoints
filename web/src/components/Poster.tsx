import type { CSSProperties } from 'react'
import { hueOf } from '../lib/format'

/**
 * The title-on-colour poster. It carries the title as text so the page reads the same with images
 * off; real posters can slot in here later without touching callers. `--h` is a stable hue per film.
 */
export function Poster({
  id,
  title,
  small = false,
  className = '',
}: {
  id: number
  title: string
  small?: boolean
  className?: string
}) {
  return (
    <div
      className={`poster${small ? ' sm' : ''} ${className}`}
      style={{ '--h': hueOf(id) } as CSSProperties}
      role="img"
      aria-label={`Placeholder poster for ${title}`}
    >
      <span>{title}</span>
    </div>
  )
}
