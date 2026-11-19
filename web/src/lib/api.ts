import type {
  CsvRow,
  Film,
  FranchiseGroup,
  ImportedFilm,
  MatchedFilm,
  Meta,
  ProfileStats,
  RecommendResponse,
} from './types'

// Same origin in production behind a proxy, or an absolute URL set at build time
// (VITE_API_URL=https://plotpoints-api.example.run.app). In dev, vite proxies /api.
const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? '/api'

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    })
  } catch {
    throw new ApiError('Could not reach PlotPoints. Check your connection and try again.', 0)
  }
  if (!res.ok) {
    let detail = `Something went wrong (${res.status}).`
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') detail = body.detail
      else if (Array.isArray(body.detail)) detail = 'That request was not valid.'
    } catch {
      /* keep the generic message */
    }
    throw new ApiError(detail, res.status)
  }
  return res.json() as Promise<T>
}

const post = <T>(path: string, body: unknown) =>
  request<T>(path, { method: 'POST', body: JSON.stringify(body) })

export interface RecommendBody {
  members: { name: string; films: Film[] }[]
  providers?: string[]
  limit?: number
  offset?: number
}

export const api = {
  meta: () => request<Meta>('/meta'),
  importLetterboxd: (username: string) =>
    post<{ username: string; entries: number; films: ImportedFilm[] }>('/import/letterboxd', {
      username,
    }),
  match: (rows: CsvRow[]) =>
    post<{
      films: MatchedFilm[]
      unmatched: { title: string; year: number | null }[]
      ambiguous: number
    }>('/match', { rows }),
  recommend: (body: RecommendBody) => post<RecommendResponse>('/recommend', body),
  profile: (films: Film[]) => post<ProfileStats>('/profile', { films }),
  franchises: (body: RecommendBody) =>
    post<{ franchises: FranchiseGroup[]; unmatched_films: number }>('/franchises', body),
  consent: (body: {
    source: 'letterboxd-username' | 'letterboxd-export'
    username?: string
    films: Film[]
  }) => post<{ stored: number; token: string }>('/consent', body),
  deleteData: (token: string) => post<{ requested: boolean }>('/delete', { token }),
}
