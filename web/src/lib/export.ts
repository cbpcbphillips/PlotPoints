import JSZip from 'jszip'
import Papa from 'papaparse'
import type { CsvRow } from './types'

/**
 * Letterboxd's "Export Your Data" zip holds several CSVs. Three matter here:
 *   watched.csv  Date, Name, Year, Letterboxd URI                          every film seen
 *   ratings.csv  Date, Name, Year, Letterboxd URI, Rating                  current rating per film
 *   diary.csv    Date, Name, Year, Letterboxd URI, Rating, Rewatch, Tags, Watched Date
 *
 * It is all parsed here, in the browser: the file never leaves the device unless the person
 * ticks the consent box, and then only the (tmdb_id, rating, rewatch) rows are sent, never the
 * file itself, reviews or tags.
 */
export type Row = Record<string, string>
export interface ExportTables {
  ratings?: Row[]
  diary?: Row[]
  watched?: Row[]
}

interface Acc {
  title: string
  year: number | null
  rating: number | null
  ratingFromRatings: boolean
  latestWatch: string
  entries: number
  rewatch: boolean
}

const toYear = (v: string | undefined) => {
  const n = Number.parseInt(v ?? '', 10)
  return Number.isFinite(n) ? n : null
}
const toRating = (v: string | undefined) => {
  const n = Number.parseFloat(v ?? '')
  return Number.isFinite(n) && n >= 0.5 && n <= 5 ? n : null
}

/**
 * Merge the three tables into one row per film.
 *
 * - The rating comes from ratings.csv when present (it is the current one); otherwise from the
 *   most recent diary entry that has one.
 * - A film is a rewatch if the diary logs it more than once or marks an entry Rewatch = Yes. A film
 *   merely appearing in several files is NOT a rewatch, which is the double-count this guards.
 */
export function combineExport(tables: ExportTables): CsvRow[] {
  const films = new Map<string, Acc>()
  const touch = (row: Row): Acc | null => {
    const title = (row['Name'] ?? '').trim()
    if (!title) return null
    const key = row['Letterboxd URI'] || `${title}|${row['Year']}`
    let acc = films.get(key)
    if (!acc) {
      acc = {
        title,
        year: toYear(row['Year']),
        rating: null,
        ratingFromRatings: false,
        latestWatch: '',
        entries: 0,
        rewatch: false,
      }
      films.set(key, acc)
    }
    return acc
  }

  for (const row of tables.watched ?? []) touch(row)

  for (const row of tables.ratings ?? []) {
    const acc = touch(row)
    const rating = toRating(row['Rating'])
    if (acc && rating != null) {
      acc.rating = rating
      acc.ratingFromRatings = true
    }
  }

  for (const row of tables.diary ?? []) {
    const acc = touch(row)
    if (!acc) continue
    acc.entries += 1
    if ((row['Rewatch'] ?? '').trim().toLowerCase() === 'yes') acc.rewatch = true
    const when = row['Watched Date'] || row['Date'] || ''
    const rating = toRating(row['Rating'])
    if (!acc.ratingFromRatings && rating != null && when >= acc.latestWatch) {
      acc.rating = rating
      acc.latestWatch = when
    }
  }

  return [...films.values()].map((a) => ({
    title: a.title,
    year: a.year,
    rating: a.rating,
    rewatch: a.rewatch || a.entries > 1,
  }))
}

const parse = (text: string): Row[] =>
  Papa.parse<Row>(text, { header: true, skipEmptyLines: true }).data

/**
 * Which table a CSV is. Inside the zip only the three exact top-level names count: watchlist.csv
 * and likes/films.csv have the same columns as watched.csv, and guessing from headers there would
 * mark every watchlist film as already seen and drop it from the recommendations. The header guess
 * is only for a loose CSV someone chose directly under some other name.
 */
function classify(name: string, rows: Row[], inZip: boolean): keyof ExportTables | null {
  const base = name.toLowerCase().split('/').pop() ?? ''
  const topLevel = !name.includes('/')
  if (base === 'ratings.csv' && (!inZip || topLevel)) return 'ratings'
  if (base === 'diary.csv' && (!inZip || topLevel)) return 'diary'
  if (base === 'watched.csv' && (!inZip || topLevel)) return 'watched'
  if (inZip) return null
  const cols = Object.keys(rows[0] ?? {})
  if (cols.includes('Watched Date')) return 'diary'
  if (cols.includes('Rating')) return 'ratings'
  if (cols.includes('Name') && cols.includes('Letterboxd URI')) return 'watched'
  return null
}

/** Read a chosen zip, or one or more of its CSVs. Throws a readable message if none fit. */
export async function readExportFiles(files: File[]): Promise<ExportTables> {
  const tables: ExportTables = {}
  const take = (name: string, text: string, inZip: boolean) => {
    const rows = parse(text)
    const kind = classify(name, rows, inZip)
    if (kind) tables[kind] = [...(tables[kind] ?? []), ...rows]
  }

  for (const file of files) {
    if (file.name.toLowerCase().endsWith('.zip')) {
      const zip = await JSZip.loadAsync(file)
      for (const [path, entry] of Object.entries(zip.files)) {
        if (!entry.dir && path.toLowerCase().endsWith('.csv')) {
          take(path, await entry.async('string'), true)
        }
      }
    } else {
      take(file.name, await file.text(), false)
    }
  }

  if (!tables.ratings && !tables.diary && !tables.watched) {
    throw new Error(
      'I could not find ratings.csv, diary.csv or watched.csv in that file. Choose the .zip from ' +
        'Letterboxd (Settings, Import & Export, Export Your Data) or one of those CSVs.',
    )
  }
  return tables
}
