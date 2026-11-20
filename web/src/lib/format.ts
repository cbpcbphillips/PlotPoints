/** 4.5 -> "rated 4.5". Null means the film is in the history but was never rated. */
export function ratedPhrase(rating: number | null): string {
  if (rating == null) return 'seen'
  return `rated ${Number.isInteger(rating) ? rating : rating.toFixed(1)}`
}

export function joinList(items: string[]): string {
  if (items.length <= 1) return items.join('')
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`
}

/** The in-app page for one film. */
export function filmPath(tmdbId: number): string {
  return `/film/${tmdbId}`
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

/** "2h 14m" for a runtime in minutes; "" when unknown. */
export function runtimeLabel(minutes: number | null): string {
  if (!minutes) return ''
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return h ? `${h}h${m ? ` ${m}m` : ''}` : `${m}m`
}

/** The film id out of a route param, or null when it is not a positive whole number. */
export function parseFilmId(param: string | undefined): number | null {
  if (!param || !/^\d+$/.test(param)) return null
  const n = Number(param)
  return n > 0 && Number.isSafeInteger(n) ? n : null
}
