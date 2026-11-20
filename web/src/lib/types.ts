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

/** The rest of a franchise folded into its best-ranked film. */
export interface Bundle {
  franchise: string
  more: number
  /** The next few by rank; `more` can be larger than this list. */
  films: { tmdb_id: number; title: string; year: number | null }[]
}

/** Why a comfort-zone pick is outside the person's usual taste (it makes no similarity claim). */
export interface Outside {
  /** The genre of the pick that the person rates least. */
  genre: string | null
  /** How many of the person's liked films are in that genre. */
  liked_in_genre: number
  liked_total: number
  /** The pick scores within the top N percent of everything that could be suggested. */
  top_percent: number
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
  backdrop_path: string | null
  franchise: string | null
  genres: string[]
  providers: string[]
  overall_rank?: number | null
  /** Set when this row stands for a whole franchise: how many other films it folds in. */
  bundle?: Bundle | null
  /** Only on the comfort-zone pick. */
  outside?: Outside
  /** Group lists only: whose turn it was when this film was picked. */
  picked_for?: string
  /** Group lists only: where the film sits in each person's own ranking (1 = their very best). */
  fit?: { member: string; top_percent: number }[]
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
  /** In how many of the top `of` picks this film is one of the three named as the reason. */
  behind: number
  /** How many top picks were counted (up to 50). */
  of: number
}

export type FacetKind = 'genre' | 'keyword' | 'director' | 'actor' | 'era'

/** How several values of one kind combine: all of them (Romance and Comedy) or any (Drama or Thriller). */
export type FacetMode = 'all' | 'any'

/** Browse: restrict a ranking to some genres, themes, directors, billed actors or decades. */
export interface Facet {
  kind: FacetKind
  values: string[]
  mode: FacetMode
}

/** What a set of filters resolved to: the catalog's spelling, and how many films match all. */
export interface FacetInfo {
  facets: Facet[]
  total: number
}

export interface FacetList {
  genres: { name: string; count: number }[]
  decades: { decade: number; count: number }[]
}

export interface Person {
  name: string
  count: number
}

export interface RecommendResponse {
  snapshot: string
  group: boolean
  providers: string[]
  results: Result[]
  /** Liked films ranked by weighted similarity; only on the first, unfiltered page of one person. */
  enjoyed: Enjoyed[] | null
  /** A varied second row: from the person's ranking, spread away from the first page. */
  branch_out?: Result[] | null
  /** A well-rated film outside the person's usual genres that still scores for them. */
  wildcard?: Result | null
  /** Set when the request asked for a facet. */
  facet?: FacetInfo | null
  has_more: boolean
  unmatched_films: number
  /** Films rated above 3 stars that are in the catalog: what the picks are measured against. */
  liked_films: number
  /** Films with any rating that are in the catalog. */
  rated_films: number
  pool_size?: number
  pool_matches?: number
}

/** What a film card shows, independent of any taste profile. */
export interface FilmCardData {
  tmdb_id: number
  media_key: string
  title: string
  year: number | null
  tmdb_rating: number | null
  runtime: number | null
  poster_path: string | null
  backdrop_path: string | null
  franchise: string | null
  genres: string[]
  providers: string[]
}

export interface FilmDetail extends FilmCardData {
  original_title: string | null
  tagline: string | null
  overview: string | null
  directors: string[]
  /** TMDB themes, a dozen at most. */
  keywords: string[]
  cast: { name: string; character: string | null }[]
  providers_as_of: string
}

/** A "more like this" film: plain cosine similarity to the one being viewed, whole percent. */
export interface SimilarFilm extends FilmCardData {
  match: number
}

/** A liked film of the viewer's that sits close to the film being viewed. */
export interface ClosestFilm {
  tmdb_id: number
  title: string
  year: number | null
  poster_path: string | null
  /** Plain cosine similarity to the viewed film, whole percent. */
  match: number
}

/** How one film sits against the viewer's own films. */
export interface FilmForMe {
  /** The viewer has already logged this film. */
  seen: boolean
  rating: number | null
  /** Mean similarity of the three closest liked films, whole percent. */
  match: number | null
  closest: ClosestFilm[]
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
  /** tmdb ids of the history's films the current snapshot does not hold */
  missing_ids: number[]
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
  /** How the row was matched: strict / loose title, a wider year window, or a TMDB lookup. */
  method?: 'strict' | 'loose' | 'wide' | 'tmdb'
}

/** A real film TMDB knows that the catalog does not hold yet (usually under the vote floor). */
export interface MissingMatch extends Film {
  title: string
  year: number | null
  tmdb_title: string | null
  tmdb_year: number | null
  votes: number
}

export interface MatchResponse {
  films: MatchedFilm[]
  missing: MissingMatch[]
  tv: { title: string; year: number | null }[]
  unmatched: { title: string; year: number | null }[]
  ambiguous: number
  lookups_skipped: number
}

/** A film from someone's history that their profile cannot use yet, and why. */
export interface MissingFilm {
  title: string
  year: number | null
  reason: 'not_in_catalog' | 'tv' | 'not_found'
  tmdb_id?: number
  votes?: number | null
}

export interface ImportedFilm extends MatchedFilm {
  in_catalog?: boolean
}
