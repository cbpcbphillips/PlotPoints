export type MediaType = 'movie' | 'tv'

/** One film in someone's history. rating is Letterboxd's 0.5-5 scale; null means seen, unrated. */
export interface Film {
  tmdb_id: number
  media_type: MediaType
  rating: number | null
  rewatch: boolean
}

export interface Because {
  title: string
  tmdb_id: number
  match: number
}

export interface Result {
  rank: number
  tmdb_id: number
  media_key: string
  title: string
  year: number | null
  /** Raw cosine similarity to the films that explain this pick, as a whole percent. */
  match: number
  /** The ranking score (hubness-corrected, about 2-4 at the top). Not a percentage. */
  score: number
  /** 100 minus the closest explaining film's similarity. A stand-in; see roadmap decision 5d. */
  novelty: number | null
  tmdb_rating: number | null
  runtime: number | null
  poster_path: string | null
  franchise: string | null
  genres: string[]
  providers: string[]
  overall_rank?: number | null
  members: { member: string; match: number; because: Because[] }[]
}

/** A film the person liked, with how well it explains their top picks. */
export interface Enjoyed {
  tmdb_id: number
  media_key: string
  title: string
  year: number | null
  poster_path: string | null
  rating: number | null
  /** Mean cosine to the top picks, whole percent. */
  avg_match: number
}

export interface RecommendResponse {
  snapshot: string
  group: boolean
  providers: string[]
  results: Result[]
  /** Liked films ranked by weighted similarity; only on the first, unfiltered page of one person. */
  enjoyed: Enjoyed[] | null
  has_more: boolean
  unmatched_films: number
  pool_size?: number
  pool_matches?: number
}

export interface SeenInFranchise {
  tmdb_id: number
  media_key: string
  title: string
  year: number | null
  rating: number | null
  tmdb_rating: number | null
  poster_path: string | null
}

export interface FranchiseGroup {
  franchise: string
  best: Result
  others: Result[]
  count: number
  seen: SeenInFranchise[]
}

export interface Share {
  name: string
  count: number
  share: number
}

export interface ProfileStats {
  films: number
  rated: number
  in_catalog: number
  not_in_catalog: number
  average_rating: number | null
  histogram: { rating: number; count: number }[]
  genres: Share[]
  eras: Share[]
  average_runtime: number | null
  average_tmdb: number | null
  top_series: { name: string; count: number } | null
  five_star: string[]
  newest: number | null
  oldest: number | null
}

export interface Meta {
  snapshot: string
  titles: number
  embedding_model: string
  providers_as_of: string
  providers: { name: string; titles: number }[]
}

export interface CsvRow {
  title: string
  year: number | null
  rating: number | null
  rewatch: boolean
}

export interface MatchedFilm extends Film {
  title: string
  year: number | null
  ambiguous?: boolean
}

export interface ImportedFilm extends MatchedFilm {
  in_catalog?: boolean
}
