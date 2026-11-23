import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { clearSavedList } from './savedLists'
import type { Film, MissingFilm } from './types'

/**
 * The only thing PlotPoints remembers about a person, and it never leaves their browser unless
 * they ticked the consent box: their films, plus the token that lets them delete a stored import.
 * There are no accounts; "switch user" is just clearing this.
 */
export interface Profile {
  name: string
  films: Film[]
  source: 'username' | 'export'
  username?: string
  importedAt: string
  matched: number
  /** films in the export the catalog does not contain */
  unmatched: number
  consentedAt?: string
  deletionToken?: string
  /** tmdb ids the person said "not for me" to; sent as a 1-star rating so they act as dislikes */
  notForMe: number[]
  /** films the profile cannot use yet (not in the catalog, TV, not found), for the History page */
  missing?: MissingFilm[]
}

const KEY = 'pp-profile'

function read(): Profile | null {
  try {
    const raw = localStorage.getItem(KEY)
    return raw ? (JSON.parse(raw) as Profile) : null
  } catch {
    return null
  }
}

function write(p: Profile | null) {
  try {
    if (p) localStorage.setItem(KEY, JSON.stringify(p))
    else {
      localStorage.removeItem(KEY)
      clearSavedList() // the saved recommendations belong to the profile and go with it
    }
  } catch {
    /* storage can be blocked (private windows); the session still works in memory */
  }
}

/** What the API is sent: the person's films, with "not for me" folded in as low ratings. */
export function effectiveFilms(p: Profile): Film[] {
  const nope = new Set(p.notForMe)
  const films = p.films.map((f) => (nope.has(f.tmdb_id) ? { ...f, rating: 1, rewatch: false } : f))
  const have = new Set(films.map((f) => f.tmdb_id))
  for (const id of nope) {
    if (!have.has(id)) films.push({ tmdb_id: id, media_type: 'movie', rating: 1, rewatch: false })
  }
  return films
}

interface Ctx {
  profile: Profile | null
  setProfile: (p: Profile | null) => void
  markNotForMe: (tmdbId: number) => void
}

const ProfileContext = createContext<Ctx | null>(null)

export function ProfileProvider({ children }: { children: ReactNode }) {
  const [profile, setState] = useState<Profile | null>(read)
  const setProfile = useCallback((p: Profile | null) => {
    write(p)
    setState(p)
  }, [])
  const markNotForMe = useCallback((id: number) => {
    setState((cur) => {
      if (!cur || cur.notForMe.includes(id)) return cur
      const next = { ...cur, notForMe: [...cur.notForMe, id] }
      write(next)
      return next
    })
  }, [])
  const value = useMemo(
    () => ({ profile, setProfile, markNotForMe }),
    [profile, setProfile, markNotForMe],
  )
  return <ProfileContext.Provider value={value}>{children}</ProfileContext.Provider>
}

export function useProfile(): Ctx {
  const ctx = useContext(ProfileContext)
  if (!ctx) throw new Error('useProfile needs a ProfileProvider')
  return ctx
}
