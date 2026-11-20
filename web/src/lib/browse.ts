import type { Facet, FacetKind } from './types'

export const KIND_LABEL: Record<FacetKind, string> = {
  genre: 'Genre',
  director: 'Director',
  actor: 'Actor',
  era: 'Decade',
}

/** The order filters read in and are written to a URL in: the first one is the path. */
export const KIND_ORDER: FacetKind[] = ['genre', 'era', 'director', 'actor']

export function parseFacetKind(param: string | undefined | null): FacetKind | null {
  return param === 'genre' || param === 'director' || param === 'actor' || param === 'era'
    ? param
    : null
}

/** The decade a year falls in: 1994 -> 1990. */
export function decadeOf(year: number): number {
  return Math.floor(year / 10) * 10
}

/** A facet value as a heading: decades read "1990s", everything else is its own name. */
export function facetTitle(kind: FacetKind, value: string): string {
  if (kind !== 'era') return value
  const d = /^(\d{4})s?$/.exec(value.trim())
  return d ? `${decadeOf(Number(d[1]))}s` : value
}

/** Filters sorted into reading order, one per kind (a later one replaces an earlier one). */
export function normalizeFacets(facets: Facet[]): Facet[] {
  const byKind = new Map<FacetKind, Facet>()
  for (const f of facets) {
    let value = f.value.trim()
    if (f.kind === 'era') {
      const d = /^(\d{4})s?$/.exec(value) // 1960, 1960s and 1964 are all the same page
      if (d) value = String(decadeOf(Number(d[1])))
    }
    if (value) byKind.set(f.kind, { kind: f.kind, value })
  }
  return KIND_ORDER.filter((k) => byKind.has(k)).map((k) => byKind.get(k)!)
}

/**
 * The in-app page for a set of filters. The first is the path (/browse/genre/Drama) and the rest
 * are the query (?era=1990), so a single filter keeps its short link and every page has one
 * canonical address, whatever order the filters were added in.
 */
export function facetsPath(facets: Facet[]): string {
  const [first, ...rest] = normalizeFacets(facets)
  if (!first) return '/browse'
  const path = `/browse/${first.kind}/${encodeURIComponent(first.value)}`
  if (!rest.length) return path
  const query = rest.map((f) => `${f.kind}=${encodeURIComponent(f.value)}`).join('&')
  return `${path}?${query}`
}

/** The in-app page for one genre, director, actor or decade. */
export function browsePath(kind: FacetKind, value: string | number): string {
  return facetsPath([{ kind, value: String(value) }])
}

/** The filters a /browse URL stands for: the path's, plus any more in the query string. */
export function facetsFromUrl(kind: FacetKind, value: string, search: string): Facet[] {
  const all: Facet[] = [{ kind, value }]
  const params = new URLSearchParams(search)
  for (const k of KIND_ORDER) {
    const v = params.get(k)
    if (k !== kind && v) all.push({ kind: k, value: v })
  }
  return normalizeFacets(all)
}

/** These filters with one added, replacing any filter of the same kind. */
export function withFacet(facets: Facet[], add: Facet): Facet[] {
  return normalizeFacets([...facets.filter((f) => f.kind !== add.kind), add])
}

/** These filters with the one of this kind taken out. */
export function withoutKind(facets: Facet[], kind: FacetKind): Facet[] {
  return facets.filter((f) => f.kind !== kind)
}
