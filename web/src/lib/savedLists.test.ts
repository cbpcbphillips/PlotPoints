import { beforeEach, describe, expect, it } from 'vitest'
import type { RecommendResponse } from './types'
import { clearSavedList, keyString, loadList, saveList } from './savedLists'

const page = (n = 1): RecommendResponse =>
  ({
    snapshot: 's',
    group: false,
    providers: [],
    results: Array.from({ length: n }, (_, i) => ({ tmdb_id: i, title: `t${i}` })),
    enjoyed: null,
    has_more: false,
    unmatched_films: 0,
    liked_films: 5,
    rated_films: 5,
  }) as unknown as RecommendResponse

const KEY = keyString(['recommend', 'when', 12, '', '', 20, ''])
const NOW = 1_700_000_000_000

beforeEach(() => localStorage.clear())

describe('saved recommendation lists', () => {
  it('round-trips a list for the same key', () => {
    saveList(KEY, page(3), NOW)
    const got = loadList(KEY, NOW + 1000)
    expect(got?.page.results).toHaveLength(3)
    expect(got?.savedAt).toBe(NOW)
  })

  it('is not used for different inputs', () => {
    saveList(KEY, page(), NOW)
    expect(loadList(keyString(['recommend', 'other']), NOW)).toBeNull()
  })

  it('expires after a week', () => {
    saveList(KEY, page(), NOW)
    expect(loadList(KEY, NOW + 6 * 86_400_000)).not.toBeNull()
    expect(loadList(KEY, NOW + 8 * 86_400_000)).toBeNull()
  })

  it('ignores a list from a future clock or an old app shape', () => {
    saveList(KEY, page(), NOW + 10 * 60_000)
    expect(loadList(KEY, NOW)).toBeNull()
    localStorage.setItem(
      'pp-recs',
      JSON.stringify({ shape: 1, key: KEY, savedAt: NOW, page: page() }),
    )
    expect(loadList(KEY, NOW)).toBeNull()
  })

  it('survives garbage and blocked storage', () => {
    localStorage.setItem('pp-recs', '{not json')
    expect(loadList(KEY, NOW)).toBeNull()
    localStorage.setItem('pp-recs', JSON.stringify({ shape: 2, key: KEY, savedAt: NOW }))
    expect(loadList(KEY, NOW)).toBeNull() // no page
  })

  it('can be cleared', () => {
    saveList(KEY, page(), NOW)
    clearSavedList()
    expect(loadList(KEY, NOW)).toBeNull()
  })
})
