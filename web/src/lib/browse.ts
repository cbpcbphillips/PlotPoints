import type { Facet, FacetKind, FacetMode } from './types'

export const KIND_LABEL: Record<FacetKind, string> = {
  genre: 'Genre',
  keyword: 'Theme',
  director: 'Director',
  actor: 'Actor',
  era: 'Decade',
}

/** The order filters read in and are written to a URL in: the first one is the path. */
export const KIND_ORDER: FacetKind[] = ['genre', 'keyword', 'era', 'director', 'actor']

/** The most values of one kind a page can combine (the API caps it the same). */
export const MAX_VALUES = 8

export function parseFacetKind(param: string | undefined | null): FacetKind | null {
  return KIND_ORDER.find((k) => k === param) ?? null
}

/** The decade a year falls in: 1994 -> 1990. */
export function decadeOf(year: number): number {
  return Math.floor(year / 10) * 10
}

/** One value as a heading: decades read "1990s", everything else is its own name. */
export function valueTitle(kind: FacetKind, value: string): string {
  if (kind !== 'era') return value
  const d = /^(\d{4})s?$/.exec(value.trim())
  return d ? `${decadeOf(Number(d[1]))}s` : value
}

/** A filter as words: "Romance and Comedy", "Drama or Thriller", "Western". */
export function facetTitle(f: Facet): string {
  const names = f.values.map((v) => valueTitle(f.kind, v))
  if (names.length < 2) return names.join('')
  return names.join(f.mode === 'any' || f.kind === 'era' ? ' or ' : ' and ')
}

/** Does this kind offer an all-of / any-of choice? Decades never do: no film is in two. */
export function hasMode(f: Facet): boolean {
  return f.kind !== 'era' && f.values.length > 1
}

/**
 * Tidy a set of filters: one per kind, in reading order, values trimmed and de-duplicated
 * ignoring case, decades reduced to the decade (1960, 1960s and 1964 are one page), no empties,
 * and a mode only where it means something.
 */
export function normalizeFacets(facets: Facet[]): Facet[] {
  const byKind = new Map<FacetKind, Facet>()
  for (const f of facets) {
    const seen = new Set<string>()
    const values: string[] = []
    for (const raw of f.values) {
      let v = raw.trim()
      if (f.kind === 'era') {
        const d = /^(\d{4})s?$/.exec(v)
        if (d) v = String(decadeOf(Number(d[1])))
      }
      if (v && !seen.has(v.toLowerCase())) {
        seen.add(v.toLowerCase())
        values.push(v)
      }
    }
    if (!values.length) continue
    const prev = byKind.get(f.kind)
    const merged = prev ? [...prev.values, ...values] : values
    byKind.set(f.kind, {
      kind: f.kind,
      values: merged.slice(0, MAX_VALUES),
      mode: f.kind === 'era' || f.mode !== 'any' ? 'all' : 'any',
    })
  }
  return KIND_ORDER.filter((k) => byKind.has(k))
    .map((k) => byKind.get(k)!)
    .map((f) => (f.values.length < 2 ? { ...f, mode: 'all' as FacetMode } : f))
}

/**
 * The in-app page for a set of filters. The first value of the first kind is the path
 * (/browse/genre/Romance); everything else is the query (?genre=Comedy&genre_mode=any&era=1990),
 * so a single filter keeps its short link and every page has one canonical address, whatever
 * order the filters were added in. "all" is the default and is never written.
 */
export function facetsPath(facets: Facet[]): string {
  const clean = normalizeFacets(facets)
  const first = clean[0]
  if (!first) return '/browse'
  const path = `/browse/${first.kind}/${encodeURIComponent(first.values[0])}`
  const query: string[] = []
  for (const f of clean) {
    const rest = f === first ? f.values.slice(1) : f.values
    for (const v of rest) query.push(`${f.kind}=${encodeURIComponent(v)}`)
    if (f.mode === 'any' && f.kind !== 'era') query.push(`${f.kind}_mode=any`)
  }
  return query.length ? `${path}?${query.join('&')}` : path
}

/** The in-app page for one genre, theme, director, actor or decade. */
export function browsePath(kind: FacetKind, value: string | number): string {
  return facetsPath([{ kind, values: [String(value)], mode: 'all' }])
}

/** The filters a /browse URL stands for: the path's value, plus any more in the query string. */
export function facetsFromUrl(kind: FacetKind, value: string, search: string): Facet[] {
  const params = new URLSearchParams(search)
  const all: Facet[] = []
  for (const k of KIND_ORDER) {
    const values = [...(k === kind ? [value] : []), ...params.getAll(k)]
    if (values.length) {
      all.push({ kind: k, values, mode: params.get(`${k}_mode`) === 'any' ? 'any' : 'all' })
    }
  }
  return normalizeFacets(all)
}

/** These filters with one value added to its kind. */
export function addValue(facets: Facet[], kind: FacetKind, value: string): Facet[] {
  const have = facets.find((f) => f.kind === kind)
  if (!have) return normalizeFacets([...facets, { kind, values: [value], mode: 'all' }])
  return normalizeFacets(
    facets.map((f) => (f.kind === kind ? { ...f, values: [...f.values, value] } : f)),
  )
}

/** These filters with one value taken out (and the kind too, if it was the last). */
export function removeValue(facets: Facet[], kind: FacetKind, value: string): Facet[] {
  const gone = normalizeFacets([{ kind, values: [value], mode: 'all' }])[0]?.values[0]
  return normalizeFacets(
    facets.map((f) =>
      f.kind === kind
        ? {
            ...f,
            values: f.values.filter((v) => v.toLowerCase() !== (gone ?? value).toLowerCase()),
          }
        : f,
    ),
  )
}

/** Swap one value of a kind for another (a single choice, like the decade picker for one decade). */
export function replaceKind(facets: Facet[], kind: FacetKind, values: string[]): Facet[] {
  const old = facets.find((f) => f.kind === kind)
  return normalizeFacets([
    ...facets.filter((f) => f.kind !== kind),
    ...(values.length ? [{ kind, values, mode: old?.mode ?? 'all' }] : []),
  ])
}

/** These filters with one kind switched between all-of and any-of. */
export function setMode(facets: Facet[], kind: FacetKind, mode: FacetMode): Facet[] {
  return normalizeFacets(facets.map((f) => (f.kind === kind ? { ...f, mode } : f)))
}

/** Is this value one of the active ones? (ignoring case; decades by their decade) */
export function hasValue(facets: Facet[], kind: FacetKind, value: string): boolean {
  const f = normalizeFacets([{ kind, values: [value], mode: 'all' }])[0]
  const want = f?.values[0]?.toLowerCase()
  return facets.some((x) => x.kind === kind && x.values.some((v) => v.toLowerCase() === want))
}
