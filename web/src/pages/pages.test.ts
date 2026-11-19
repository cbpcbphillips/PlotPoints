import { describe, expect, it } from 'vitest'
import type { FranchiseGroup, Result } from '../lib/types'
import { entriesOf, sortEntries } from './Franchises'
import { mergePicks } from './Streaming'

const film = (id: number, score: number, over: Partial<Result> = {}): Result => ({
  rank: id,
  tmdb_id: id,
  media_key: `k${id}`,
  title: `Film ${id}`,
  year: 2000 + id,
  match: 50,
  score,
  novelty: 40,
  tmdb_rating: 7,
  runtime: 100,
  poster_path: null,
  backdrop_path: null,
  franchise: null,
  genres: [],
  providers: [],
  members: [],
  ...over,
})

describe('mergePicks', () => {
  it('unions the services, best score first, and notes every service a film is on', () => {
    const picks = mergePicks(
      ['Max', 'Netflix'],
      [
        [film(1, 3.0), film(2, 2.0)],
        [film(3, 4.0), film(2, 2.0)],
      ],
    )
    expect(picks.map((p) => p.r.tmdb_id)).toEqual([3, 1, 2])
    expect(picks.find((p) => p.r.tmdb_id === 2)?.services).toEqual(['Max', 'Netflix'])
  })

  it('tolerates a service that has not loaded yet', () => {
    expect(mergePicks(['Max', 'Netflix'], [[film(1, 3)], undefined]).map((p) => p.r.tmdb_id)).toEqual([1])
  })
})

describe('franchise shelves', () => {
  const group: FranchiseGroup = {
    franchise: 'Alpha',
    best: film(1, 3.1, { year: 2005 }),
    others: [film(2, 2.4, { year: 2001 })],
    count: 2,
    seen: [
      { tmdb_id: 9, media_key: 'k9', title: 'Seen One', year: 2003, rating: 4.5, tmdb_rating: 7, poster_path: null },
      { tmdb_id: 8, media_key: 'k8', title: 'Seen Two', year: 1999, rating: null, tmdb_rating: 6, poster_path: null },
    ],
  }

  it('lists unseen and seen films together and marks the best', () => {
    const all = entriesOf(group)
    expect(all).toHaveLength(4)
    expect(all.filter((e) => e.best).map((e) => e.id)).toEqual([1])
    expect(all.filter((e) => e.seen).map((e) => e.id).sort()).toEqual([8, 9])
  })

  it('orders by release year, or by score with seen films last by your rating', () => {
    const all = entriesOf(group)
    expect(sortEntries(all, 'year').map((e) => e.id)).toEqual([8, 2, 9, 1])
    expect(sortEntries(all, 'score').map((e) => e.id)).toEqual([1, 2, 9, 8])
  })
})
