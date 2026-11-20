import { describe, expect, it } from 'vitest'
import {
  browsePath,
  decadeOf,
  facetTitle,
  facetsFromUrl,
  facetsPath,
  parseFacetKind,
  withFacet,
  withoutKind,
} from './browse'

describe('browse helpers', () => {
  it('builds paths that survive spaces and slashes', () => {
    expect(browsePath('genre', 'Science Fiction')).toBe('/browse/genre/Science%20Fiction')
    expect(browsePath('director', 'Jean-Pierre Jeunet')).toBe(
      '/browse/director/Jean-Pierre%20Jeunet',
    )
    expect(browsePath('era', 1990)).toBe('/browse/era/1990')
    expect(decodeURIComponent(browsePath('actor', 'A/B').split('/').pop()!)).toBe('A/B')
  })

  it('knows the four kinds and nothing else', () => {
    for (const k of ['genre', 'director', 'actor', 'era']) expect(parseFacetKind(k)).toBe(k)
    expect(parseFacetKind('mood')).toBeNull()
    expect(parseFacetKind(undefined)).toBeNull()
  })

  it('rounds years down to their decade', () => {
    expect(decadeOf(1994)).toBe(1990)
    expect(decadeOf(2000)).toBe(2000)
    expect(decadeOf(1979)).toBe(1970)
  })

  it('titles decades as 1990s and leaves names alone', () => {
    expect(facetTitle('era', '1994')).toBe('1990s')
    expect(facetTitle('era', '1990s')).toBe('1990s')
    expect(facetTitle('genre', 'Drama')).toBe('Drama')
  })
})

describe('combined filters in the URL', () => {
  const genre = { kind: 'genre', value: 'Drama' } as const
  const era = { kind: 'era', value: '1990' } as const
  const dir = { kind: 'director', value: 'Jean-Pierre Jeunet' } as const

  it('keeps a single filter on its short path', () => {
    expect(facetsPath([genre])).toBe('/browse/genre/Drama')
    expect(facetsPath([])).toBe('/browse')
  })

  it('puts the first filter in the path and the rest in the query, in a fixed order', () => {
    expect(facetsPath([era, genre])).toBe('/browse/genre/Drama?era=1990')
    expect(facetsPath([dir, era, genre])).toBe(
      '/browse/genre/Drama?era=1990&director=Jean-Pierre%20Jeunet',
    )
  })

  it('round-trips through the URL whatever order they were added in', () => {
    const url = facetsPath([dir, genre, era])
    const [path, search] = url.split('?')
    const [, , kind, value] = path.split('/')
    const back = facetsFromUrl(kind as 'genre', decodeURIComponent(value), `?${search}`)
    expect(back).toEqual([genre, era, dir])
  })

  it('ignores unknown or empty query filters and a repeat of the path kind', () => {
    expect(facetsFromUrl('genre', 'Drama', '?mood=sad&era=&genre=Crime')).toEqual([genre])
  })

  it('adds a filter, replacing one of the same kind, and removes by kind', () => {
    expect(withFacet([genre, era], { kind: 'genre', value: 'Crime' })).toEqual([
      { kind: 'genre', value: 'Crime' },
      era,
    ])
    expect(withoutKind([genre, era], 'genre')).toEqual([era])
    expect(facetsPath(withoutKind([genre], 'genre'))).toBe('/browse')
  })
})

describe('decade filters', () => {
  it('treat 1960, 1960s and 1964 as one page', () => {
    for (const v of ['1960', '1960s', '1964']) {
      expect(facetsPath([{ kind: 'era', value: v }])).toBe('/browse/era/1960')
    }
  })
})
