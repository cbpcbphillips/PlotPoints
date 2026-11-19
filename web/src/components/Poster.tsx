import { useState, type CSSProperties } from 'react'
import { hueOf } from '../lib/format'

/** TMDB's image CDN. Sizes are TMDB's own steps; w342 covers the hero at 2x, w185 the shelves. */
export const tmdbImage = (path: string, size: 'w185' | 'w342' | 'w780' | 'w1280') =>
  `https://image.tmdb.org/t/p/${size}${path}`

/**
 * A film's poster: the real TMDB image when there is one, laid over the title-on-colour
 * placeholder. The placeholder stays underneath, so a slow, blocked or missing image still leaves
 * a readable tile with the title, and nothing shifts when the image arrives.
 */
export function Poster({
  id,
  title,
  path,
  small = false,
  className = '',
}: {
  id: number
  title: string
  path?: string | null
  small?: boolean
  className?: string
}) {
  const [failed, setFailed] = useState(false)
  const showImage = Boolean(path) && !failed
  return (
    <div
      className={`poster${small ? ' sm' : ''} ${className}`}
      style={{ '--h': hueOf(id) } as CSSProperties}
      role="img"
      aria-label={`Poster for ${title}`}
    >
      <span>{title}</span>
      {showImage && (
        <img
          src={tmdbImage(path as string, small ? 'w185' : 'w342')}
          alt=""
          loading="lazy"
          decoding="async"
          onError={() => setFailed(true)}
          className="absolute inset-0 h-full w-full object-cover"
        />
      )}
    </div>
  )
}
