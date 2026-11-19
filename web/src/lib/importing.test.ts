import { describe, expect, it } from 'vitest'
import { fromFeed, fromMatch, mergeMissing, stillMissing } from './importing'
import type { MatchResponse } from './types'

const response: MatchResponse = {
  films: [{ tmdb_id: 1, media_type: 'movie', rating: 4, rewatch: false, title: 'In', year: 2000 }],
  missing: [
    {
      tmdb_id: 9,
      media_type: 'movie',
      rating: 5,
      rewatch: false,
      title: 'Golden Boy',
      year: 1995,
      tmdb_title: 'Golden Boy',
      tmdb_year: 1996,
      votes: 5,
    },
  ],
  tv: [{ title: 'Baby Reindeer', year: 2024 }],
  unmatched: [{ title: 'Nothing', year: 1999 }],
  ambiguous: 0,
  lookups_skipped: 0,
}

describe('importing', () => {
  it('keeps missing films with ids so they count once the catalog has them', () => {
    const out = fromMatch(response)
    expect(out.films.map((f) => f.tmdb_id)).toEqual([1, 9])
    expect(out.missing.map((m) => m.reason)).toEqual(['not_in_catalog', 'tv', 'not_found'])
  })

  it('treats RSS films outside the catalog as missing', () => {
    const out = fromFeed([
      { tmdb_id: 1, media_type: 'movie', rating: 4, rewatch: false, title: 'A', year: 2000, in_catalog: true },
      { tmdb_id: 2, media_type: 'movie', rating: 5, rewatch: false, title: 'B', year: 1980, in_catalog: false },
    ])
    expect(out.films).toHaveLength(2)
    expect(out.missing).toEqual([{ title: 'B', year: 1980, reason: 'not_in_catalog', tmdb_id: 2 }])
  })

  it('merges lists one entry per film and drops films a later snapshot added', () => {
    const merged = mergeMissing(fromMatch(response).missing, fromMatch(response).missing)
    expect(merged).toHaveLength(3)
    expect(stillMissing(merged, [9]).map((m) => m.title)).toEqual(['Golden Boy', 'Baby Reindeer', 'Nothing'])
    expect(stillMissing(merged, []).map((m) => m.title)).toEqual(['Baby Reindeer', 'Nothing'])
  })
})
