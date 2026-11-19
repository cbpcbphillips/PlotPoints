/** 4.5 -> "rated 4.5". Null means the film is in the history but was never rated. */
export function ratedPhrase(rating: number | null): string {
  if (rating == null) return 'seen'
  return `rated ${Number.isInteger(rating) ? rating : rating.toFixed(1)}`
}

export function joinList(items: string[]): string {
  if (items.length <= 1) return items.join('')
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`
}

export function tmdbWatchUrl(id: number): string {
  return `https://www.themoviedb.org/movie/${id}/watch?locale=US`
}

/** Hue (0-359) of a film's placeholder poster; stable per film so it never changes between visits. */
export function hueOf(id: number): number {
  return (Math.abs(id) * 47) % 360
}

export function prettyDate(iso: string): string {
  // A date-only string ("2026-11-16") is parsed as UTC midnight, which is the previous evening in
  // the Americas. Build it as a local date instead so the day shown is the day stored.
  const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso)
  const d = dateOnly
    ? new Date(Number(dateOnly[1]), Number(dateOnly[2]) - 1, Number(dateOnly[3]))
    : new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })
}
