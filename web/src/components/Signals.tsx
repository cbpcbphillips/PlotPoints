import type { CSSProperties } from 'react'
import type { Result } from '../lib/types'

/** Letterboxd half-star rating as filled stars, a half glyph, and dimmed empties. */
export function Stars({ rating }: { rating: number }) {
  const full = Math.floor(rating)
  const half = rating - full >= 0.5
  return (
    <span className="stars" role="img" aria-label={`${rating} out of 5`}>
      {'★'.repeat(full)}
      {half && '½'}
      {Array.from({ length: 5 - full - (half ? 1 : 0) }, (_, i) => (
        <span key={i} className="off">
          ★
        </span>
      ))}
    </span>
  )
}

/** The ranking score, shown as a plain number. It is not a percentage and has no ring. */
export function Gauge({ score }: { score: number }) {
  return (
    <div className="gauge">
      <b>{score.toFixed(1)}</b>
      <small>score</small>
    </div>
  )
}

/** Match percent, novelty and TMDB rating, each with its colour dot. */
export function Sig({ r }: { r: Result }) {
  return (
    <div className="sig" aria-label="Signals">
      <span className="s1">
        Match <b>{r.match}%</b>
      </span>
      {r.novelty != null && (
        <span className="s2">
          Novelty <b>{r.novelty}</b>
        </span>
      )}
      {r.tmdb_rating != null && (
        <span className="s3">
          TMDB <b>{r.tmdb_rating.toFixed(1)}</b>
        </span>
      )}
    </div>
  )
}

// Each signal has its own shape as well as its colour, so they can be told apart without colour
// (WCAG 1.4.1): match is a circle, novelty a diamond, the TMDB rating a square.
const SHAPE: Record<string, CSSProperties> = {
  coral: { borderRadius: '50%' },
  mint: { borderRadius: 1, transform: 'rotate(45deg) scale(0.85)' },
  sky: { borderRadius: 1 },
}

const dot = (color: string, strength: number): CSSProperties => ({
  background: `var(--${color})`,
  opacity: 0.25 + Math.min(Math.max(strength, 0), 1) * 0.75,
  ...SHAPE[color],
})

/** The three signal values under a card, each dot's opacity showing how strong it is. */
export function SignalRow({ r }: { r: Result }) {
  const items: [string, string, string, number][] = [
    ['coral', 'Match', `${r.match}%`, r.match / 100],
  ]
  if (r.novelty != null) items.push(['mint', 'Novelty', String(r.novelty), r.novelty / 100])
  if (r.tmdb_rating != null) {
    items.push(['sky', 'TMDB rating', r.tmdb_rating.toFixed(1), r.tmdb_rating / 10])
  }
  return (
    <div className="dv">
      {items.map(([color, name, text, strength]) => (
        <span key={color} title={name}>
          <i style={dot(color, strength)} aria-hidden="true" />
          <span className="sr-only">{name} </span>
          {text}
        </span>
      ))}
    </div>
  )
}
