import type {
  CsvRow,
  Facet,
  FacetList,
  Film,
  FilmDetail,
  FilmForMe,
  FranchiseGroup,
  ImportedFilm,
  MatchResponse,
  Meta,
  Person,
  ProfileStats,
  RecommendResponse,
  SimilarFilm,
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
  /** One row per franchise (best film plus a count of the rest). */
  bundle?: boolean
  /** Size of the varied second row; honoured on the first, unfiltered page only. */
  branch_out?: number
  /** Browse: only films matching all of these (one per kind). */
  facets?: Facet[]
}

export const api = {
  meta: () => request<Meta>('/meta'),
  film: (id: number) => request<FilmDetail>(`/film/${id}`),
  filmForMe: (id: number, films: Film[]) => post<FilmForMe>(`/film/${id}/for-me`, { films }),
  similar: (id: number, limit = 12) =>
    request<{ films: SimilarFilm[] }>(`/film/${id}/similar?limit=${limit}`),
  importLetterboxd: (username: string) =>
    post<{ username: string; entries: number; films: ImportedFilm[] }>('/import/letterboxd', {
      username,
    }),
  match: (rows: CsvRow[]) =>
    post<MatchResponse>('/match', { rows }),
  facets: () => request<FacetList>('/facets'),
  keywords: (q = '', limit = 12) =>
    request<{ keywords: Person[] }>(`/keywords?q=${encodeURIComponent(q)}&limit=${limit}`),
  people: (kind: 'director' | 'actor', q = '', limit = 12) =>
    request<{ people: Person[] }>(
      `/people?kind=${kind}&q=${encodeURIComponent(q)}&limit=${limit}`,
    ),
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
