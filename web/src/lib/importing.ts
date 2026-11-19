import type { Film, ImportedFilm, MatchResponse, MissingFilm } from './types'

export interface ImportOutcome {
  /** Everything with a TMDB id, including films the catalog lacks: they start counting on their
   * own once a later snapshot holds them, so they are kept rather than dropped. */
  films: Film[]
  /** Films the profile cannot use yet, with the reason, for the History page. */
  missing: MissingFilm[]
}

const film = (f: Film): Film => ({
  tmdb_id: f.tmdb_id,
  media_type: f.media_type,
  rating: f.rating,
  rewatch: f.rewatch,
})

/** An export's /match answer as profile films plus a "can't use yet" list. */
export function fromMatch(m: MatchResponse): ImportOutcome {
  return {
    films: [...m.films.map(film), ...m.missing.map(film)],
    missing: [
      ...m.missing.map((x) => ({
        title: x.title,
        year: x.year,
        reason: 'not_in_catalog' as const,
        tmdb_id: x.tmdb_id,
        votes: x.votes,
      })),
      ...m.tv.map((x) => ({ title: x.title, year: x.year, reason: 'tv' as const })),
      ...m.unmatched.map((x) => ({ title: x.title, year: x.year, reason: 'not_found' as const })),
    ],
  }
}

/** An RSS import: every film already has an id; `in_catalog: false` ones are not usable yet. */
export function fromFeed(films: ImportedFilm[]): ImportOutcome {
  return {
    films: films.map(film),
    missing: films
      .filter((f) => f.in_catalog === false)
      .map((f) => ({ title: f.title, year: f.year, reason: 'not_in_catalog' as const, tmdb_id: f.tmdb_id })),
  }
}

/** Merge a new "can't use yet" list into an existing one, one entry per film. */
export function mergeMissing(prev: MissingFilm[], next: MissingFilm[]): MissingFilm[] {
  const key = (m: MissingFilm) => (m.tmdb_id != null ? `id:${m.tmdb_id}` : `t:${m.title}|${m.year}`)
  const out = new Map(prev.map((m) => [key(m), m]))
  for (const m of next) out.set(key(m), m)
  return [...out.values()]
}

/**
 * What still cannot be used, given which ids the current snapshot lacks. A "not in the catalog"
 * film drops off the list once a pipeline run has added it.
 */
export function stillMissing(missing: MissingFilm[], missingIds: number[]): MissingFilm[] {
  const lacking = new Set(missingIds)
  return missing.filter((m) => m.reason !== 'not_in_catalog' || (m.tmdb_id != null && lacking.has(m.tmdb_id)))
}
