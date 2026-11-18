import { describe, expect, it } from 'vitest'
import { combineExport } from './export'

const uri = (n: number) => `https://boxd.it/${n}`

describe('combineExport', () => {
  it('merges the three tables into one row per film', () => {
    const rows = combineExport({
      watched: [
        { Name: 'Interstellar', Year: '2014', 'Letterboxd URI': uri(1) },
        { Name: 'Seen Only', Year: '2001', 'Letterboxd URI': uri(2) },
      ],
      ratings: [{ Name: 'Interstellar', Year: '2014', 'Letterboxd URI': uri(1), Rating: '4.5' }],
    })
    expect(rows).toHaveLength(2)
    expect(rows.find((r) => r.title === 'Interstellar')?.rating).toBe(4.5)
    expect(rows.find((r) => r.title === 'Seen Only')?.rating).toBeNull()
  })

  it('prefers the current rating over an older diary rating', () => {
    const [row] = combineExport({
      ratings: [{ Name: 'X', Year: '2000', 'Letterboxd URI': uri(1), Rating: '2' }],
      diary: [
        { Name: 'X', Year: '2000', 'Letterboxd URI': uri(1), Rating: '5', 'Watched Date': '2020-01-01' },
      ],
    })
    expect(row.rating).toBe(2)
  })

  it('takes the latest diary rating when there is no ratings.csv row', () => {
    const [row] = combineExport({
      diary: [
        { Name: 'X', Year: '2000', 'Letterboxd URI': uri(1), Rating: '3', 'Watched Date': '2019-05-01' },
        { Name: 'X', Year: '2000', 'Letterboxd URI': uri(1), Rating: '4.5', 'Watched Date': '2022-05-01' },
      ],
    })
    expect(row.rating).toBe(4.5)
  })

  it('treats two diary entries, or a Rewatch=Yes flag, as a rewatch', () => {
    const rows = combineExport({
      diary: [
        { Name: 'Twice', Year: '2000', 'Letterboxd URI': uri(1), Rating: '4', Rewatch: '', 'Watched Date': '2019-01-01' },
        { Name: 'Twice', Year: '2000', 'Letterboxd URI': uri(1), Rating: '4', Rewatch: '', 'Watched Date': '2020-01-01' },
        { Name: 'Flagged', Year: '2001', 'Letterboxd URI': uri(2), Rating: '5', Rewatch: 'Yes', 'Watched Date': '2020-01-01' },
        { Name: 'Once', Year: '2002', 'Letterboxd URI': uri(3), Rating: '5', Rewatch: '', 'Watched Date': '2020-01-01' },
      ],
    })
    const by = Object.fromEntries(rows.map((r) => [r.title, r.rewatch]))
    expect(by).toEqual({ Twice: true, Flagged: true, Once: false })
  })

  it('does not call a film a rewatch just because it appears in several files', () => {
    const [row] = combineExport({
      watched: [{ Name: 'X', Year: '2000', 'Letterboxd URI': uri(1) }],
      ratings: [{ Name: 'X', Year: '2000', 'Letterboxd URI': uri(1), Rating: '4' }],
      diary: [{ Name: 'X', Year: '2000', 'Letterboxd URI': uri(1), Rating: '4', 'Watched Date': '2020-01-01' }],
    })
    expect(row.rewatch).toBe(false)
  })

  it('keeps two different films that share a title apart', () => {
    const rows = combineExport({
      watched: [
        { Name: 'Good Boy', Year: '2003', 'Letterboxd URI': uri(1) },
        { Name: 'Good Boy', Year: '2025', 'Letterboxd URI': uri(2) },
      ],
    })
    expect(rows.map((r) => r.year).sort()).toEqual([2003, 2025])
  })

  it('ignores out-of-range ratings and blank names', () => {
    const rows = combineExport({
      ratings: [
        { Name: 'X', Year: '2000', 'Letterboxd URI': uri(1), Rating: '7' },
        { Name: ' ', Year: '2000', 'Letterboxd URI': uri(2), Rating: '3' },
      ],
    })
    expect(rows).toHaveLength(1)
    expect(rows[0].rating).toBeNull()
  })
})

describe('readExportFiles', () => {
  it('reads the CSVs out of a Letterboxd zip, ignoring everything else in it', async () => {
    const { default: JSZip } = await import('jszip')
    const { readExportFiles } = await import('./export')
    const zip = new JSZip()
    zip.file('ratings.csv', 'Date,Name,Year,Letterboxd URI,Rating\n2024-01-01,Heat,1995,https://boxd.it/1,4.5\n')
    zip.file('diary.csv', 'Date,Name,Year,Letterboxd URI,Rating,Rewatch,Tags,Watched Date\n2024-01-02,Heat,1995,https://boxd.it/1,4.5,Yes,,2024-01-02\n')
    zip.file('watched.csv', 'Date,Name,Year,Letterboxd URI\n2024-01-01,Heat,1995,https://boxd.it/1\n2024-01-01,Alien,1979,https://boxd.it/2\n')
    zip.file('reviews.csv', 'Date,Name\nx,y\n')
    zip.file('lists/favorites.csv', 'Position,Name\n1,Heat\n')
    // same columns as watched.csv, but NOT films the person has seen: must not be read as such
    zip.file('watchlist.csv', 'Date,Name,Year,Letterboxd URI\n2024-01-01,Unwatched Film,2020,https://boxd.it/9\n')
    zip.file('likes/films.csv', 'Date,Name,Year,Letterboxd URI\n2024-01-01,Liked Film,2021,https://boxd.it/8\n')
    const bytes = await zip.generateAsync({ type: 'arraybuffer' })
    const tables = await readExportFiles([new File([bytes], 'letterboxd-export.zip')])
    const rows = combineExport(tables)
    expect(rows.map((r) => r.title).sort()).toEqual(['Alien', 'Heat'])
    const heat = rows.find((r) => r.title === 'Heat')!
    expect(heat).toMatchObject({ year: 1995, rating: 4.5, rewatch: true })
  })

  it('says what to do when the file is not an export', async () => {
    const { readExportFiles } = await import('./export')
    await expect(
      readExportFiles([new File(['hello'], 'notes.csv', { type: 'text/csv' })]),
    ).rejects.toThrow(/ratings\.csv, diary\.csv or watched\.csv/)
  })
})
