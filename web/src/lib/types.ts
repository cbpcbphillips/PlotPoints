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
  tmdb_rating: number | null
  runtime: number | null
  poster_path: string | null
  franchise: string | null
  genres: string[]
  providers: string[]
  overall_rank?: number | null
  members: { member: string; match: number; because: Because[] }[]
}

export interface RecommendResponse {
  snapshot: string
  group: boolean
  providers: string[]
  results: Result[]
  has_more: boolean
  unmatched_films: number
  pool_size?: number
  pool_matches?: number
}

export interface FranchiseGroup {
  franchise: string
  best: Result
  others: Result[]
  count: number
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
