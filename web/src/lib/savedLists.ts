import type { RecommendResponse } from './types'

/**
 * The last recommendation list, kept in this browser so a returning visitor sees it straight away
 * (and does not wait for a sleeping server) while a fresh one loads behind it. It is the same kind
 * of data as the profile itself, which already lives here, and it goes when the profile does.
 *
 * Only the first page of the main For You list is saved. A saved list is used only if it was made
 * for exactly the same inputs (the query key), is less than a week old, and was written by this
 * version of the app: bump `SHAPE` whenever the API's response changes in a way the page reads.
 */
const KEY = 'pp-recs'
const SHAPE = 2
const MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000

interface Saved {
  shape: number
  key: string
  savedAt: number
  page: RecommendResponse
}

export function keyString(queryKey: readonly unknown[]): string {
  return JSON.stringify(queryKey)
}

export function saveList(key: string, page: RecommendResponse, now = Date.now()): void {
  try {
    const record: Saved = { shape: SHAPE, key, savedAt: now, page }
    localStorage.setItem(KEY, JSON.stringify(record))
  } catch {
    /* storage full or blocked: the list just will not be remembered */
  }
}

/** The saved first page for exactly this key, or null. */
export function loadList(
  key: string,
  now = Date.now(),
): { page: RecommendResponse; savedAt: number } | null {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return null
    const saved = JSON.parse(raw) as Partial<Saved>
    if (
      saved.shape !== SHAPE ||
      saved.key !== key ||
      typeof saved.savedAt !== 'number' ||
      !saved.page ||
      !Array.isArray(saved.page.results) ||
      now - saved.savedAt > MAX_AGE_MS ||
      saved.savedAt > now + 60_000
    ) {
      return null
    }
    return { page: saved.page, savedAt: saved.savedAt }
  } catch {
    return null
  }
}

export function clearSavedList(): void {
  try {
    localStorage.removeItem(KEY)
  } catch {
    /* nothing to do */
  }
}
