import { describe, expect, it } from 'vitest'
import type { Facet } from './types'
import {
  addValue,
  browsePath,
  decadeOf,
  facetTitle,
  facetsFromUrl,
  facetsPath,
  hasMode,
  hasValue,
  normalizeFacets,
  parseFacetKind,
  removeValue,
  replaceKind,
  setMode,
  valueTitle,
} from './browse'

const f = (kind: Facet['kind'], values: string[], mode: Facet['mode'] = 'all'): Facet => ({
  kind,
  values,
  mode,
})

describe('single filters', () => {
  it('build paths that survive spaces and slashes', () => {
    expect(browsePath('genre', 'Science Fiction')).toBe('/browse/genre/Science%20Fiction')
    expect(browsePath('director', 'Jean-Pierre Jeunet')).toBe(
      '/browse/director/Jean-Pierre%20Jeunet',
    )
    expect(browsePath('keyword', 'time travel')).toBe('/browse/keyword/time%20travel')
    expect(decodeURIComponent(browsePath('actor', 'A/B').split('/').pop()!)).toBe('A/B')
  })

  it('know the five kinds and nothing else', () => {
    for (const k of ['genre', 'keyword', 'director', 'actor', 'era']) {
      expect(parseFacetKind(k)).toBe(k)
    }
    expect(parseFacetKind('mood')).toBeNull()
    expect(parseFacetKind(undefined)).toBeNull()
  })

  it('round years down to their decade and title decades as 1990s', () => {
    expect(decadeOf(1994)).toBe(1990)
    expect(valueTitle('era', '1994')).toBe('1990s')
    expect(valueTitle('genre', 'Drama')).toBe('Drama')
  })

  it('treat 1960, 1960s and 1964 as one page', () => {
    for (const v of ['1960', '1960s', '1964']) {
      expect(facetsPath([f('era', [v])])).toBe('/browse/era/1960')
    }
  })
})

describe('several values of one kind', () => {
  it('write and / or titles', () => {
    expect(facetTitle(f('genre', ['Romance', 'Comedy']))).toBe('Romance and Comedy')
    expect(facetTitle(f('genre', ['Drama', 'Thriller'], 'any'))).toBe('Drama or Thriller')
    expect(facetTitle(f('era', ['1980', '1990']))).toBe('1980s or 1990s')
    expect(facetTitle(f('genre', ['Western']))).toBe('Western')
  })

  it('put the first value in the path, the rest and the mode in the query', () => {
    expect(facetsPath([f('genre', ['Romance', 'Comedy'])])).toBe(
      '/browse/genre/Romance?genre=Comedy',
    )
    expect(facetsPath([f('genre', ['Drama', 'Thriller'], 'any')])).toBe(
      '/browse/genre/Drama?genre=Thriller&genre_mode=any',
    )
  })

  it('never write a mode for one value, or for decades', () => {
    expect(facetsPath([f('genre', ['Drama'], 'any')])).toBe('/browse/genre/Drama')
    expect(facetsPath([f('era', ['1980', '1990'], 'any')])).toBe('/browse/era/1980?era=1990')
    expect(hasMode(f('genre', ['Drama']))).toBe(false)
    expect(hasMode(f('era', ['1980', '1990']))).toBe(false)
    expect(hasMode(f('genre', ['Drama', 'Crime']))).toBe(true)
  })

  it('round-trip through the URL', () => {
    const want = [
      f('genre', ['Drama', 'Thriller'], 'any'),
      f('keyword', ['heist']),
      f('era', ['1990']),
      f('director', ['Jean-Pierre Jeunet']),
    ]
    const url = facetsPath(want)
    const [path, search] = url.split('?')
    const [, , kind, value] = path.split('/')
    expect(facetsFromUrl(kind as 'genre', decodeURIComponent(value), `?${search}`)).toEqual(want)
  })

  it('ignore unknown kinds, empty values, and repeats ignoring case', () => {
    expect(facetsFromUrl('genre', 'Drama', '?mood=sad&era=&genre=drama&genre=Crime')).toEqual([
      f('genre', ['Drama', 'Crime']),
    ])
  })

  it('cap a kind at eight values', () => {
    const many = Array.from({ length: 12 }, (_, i) => `g${i}`)
    expect(normalizeFacets([f('genre', many)])[0].values).toHaveLength(8)
  })
})

describe('editing filters', () => {
  it('adds, removes and de-duplicates values', () => {
    const one = [f('genre', ['Romance'])]
    const two = addValue(one, 'genre', 'Comedy')
    expect(two).toEqual([f('genre', ['Romance', 'Comedy'])])
    expect(addValue(two, 'genre', 'comedy')).toEqual(two)
    expect(removeValue(two, 'genre', 'romance')).toEqual([f('genre', ['Comedy'])])
    expect(removeValue(one, 'genre', 'Romance')).toEqual([])
    expect(facetsPath(removeValue(one, 'genre', 'Romance'))).toBe('/browse')
  })

  it('adds a kind that was not there and keeps reading order', () => {
    const out = addValue([f('director', ['Ada'])], 'genre', 'Drama')
    expect(out.map((x) => x.kind)).toEqual(['genre', 'director'])
  })

  it('switches a kind between all and any, and drops the mode when it has one value', () => {
    const two = [f('genre', ['Drama', 'Thriller'])]
    expect(setMode(two, 'genre', 'any')[0].mode).toBe('any')
    expect(removeValue(setMode(two, 'genre', 'any'), 'genre', 'Thriller')[0].mode).toBe('all')
  })

  it('replaces a whole kind', () => {
    expect(replaceKind([f('genre', ['A', 'B'])], 'genre', ['C'])).toEqual([f('genre', ['C'])])
    expect(replaceKind([f('genre', ['A'])], 'genre', [])).toEqual([])
  })

  it('knows which values are on (decades by their decade)', () => {
    const on = [f('genre', ['Drama']), f('era', ['1990'])]
    expect(hasValue(on, 'genre', 'drama')).toBe(true)
    expect(hasValue(on, 'genre', 'Crime')).toBe(false)
    expect(hasValue(on, 'era', '1994')).toBe(true)
    expect(hasValue(on, 'era', '2000')).toBe(false)
  })
})
