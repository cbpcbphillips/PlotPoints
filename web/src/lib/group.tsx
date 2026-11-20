import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import type { Film } from './types'

/**
 * The other people in a "Watch together" session. Like the profile, they live only in this
 * browser: their films are sent to the API to rank one list and are not stored there.
 */
export interface GroupMember {
  name: string
  films: Film[]
  source: 'username' | 'export'
  addedAt: string
}

/** The API ranks up to six people; one of them is always the person using the site. */
export const MAX_OTHERS = 5
export const MAX_NAME = 40

const KEY = 'pp-group'

function isMember(m: unknown): m is GroupMember {
  const x = m as GroupMember
  return (
    !!x &&
    typeof x.name === 'string' &&
    x.name.length > 0 &&
    x.name.length <= MAX_NAME &&
    Array.isArray(x.films)
  )
}

function read(): GroupMember[] {
  try {
    const raw = localStorage.getItem(KEY)
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed.filter(isMember).slice(0, MAX_OTHERS) : []
  } catch {
    return []
  }
}

function write(members: GroupMember[]) {
  try {
    if (members.length) localStorage.setItem(KEY, JSON.stringify(members))
    else localStorage.removeItem(KEY)
  } catch {
    /* blocked storage: the group still works until the tab closes */
  }
}

/**
 * A name nobody in `taken` has (ignoring case), so two "Sam"s become "Sam" and "Sam 2". The API
 * refuses two members with one name, and a list that says "Sam" twice is no use to anyone.
 */
export function uniqueName(wanted: string, taken: string[]): string {
  const base = (wanted.trim() || 'Guest').slice(0, MAX_NAME - 4)
  const used = new Set(taken.map((t) => t.toLowerCase()))
  if (!used.has(base.toLowerCase())) return base
  for (let n = 2; ; n++) {
    const candidate = `${base} ${n}`
    if (!used.has(candidate.toLowerCase())) return candidate
  }
}

interface Ctx {
  members: GroupMember[]
  add: (m: GroupMember) => void
  remove: (name: string) => void
  clear: () => void
}

const GroupContext = createContext<Ctx | null>(null)

export function GroupProvider({ children }: { children: ReactNode }) {
  const [members, setMembers] = useState<GroupMember[]>(read)
  const commit = useCallback((next: GroupMember[]) => {
    write(next)
    setMembers(next)
  }, [])
  const value = useMemo<Ctx>(
    () => ({
      members,
      add: (m) => commit([...members, m].slice(0, MAX_OTHERS)),
      remove: (name) => commit(members.filter((x) => x.name !== name)),
      clear: () => commit([]),
    }),
    [members, commit],
  )
  return <GroupContext.Provider value={value}>{children}</GroupContext.Provider>
}

export function useGroup(): Ctx {
  const ctx = useContext(GroupContext)
  if (!ctx) throw new Error('useGroup needs a GroupProvider')
  return ctx
}
