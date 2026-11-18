import { useRef, useState, type DragEvent, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import { combineExport, readExportFiles } from '../lib/export'
import { useProfile, type Profile } from '../lib/profile'
import type { Film } from '../lib/types'

/**
 * Import a Letterboxd history, by export (whole history) or by username (latest ~50 entries).
 *
 * `mode="replace"` is the first visit and "switch user": it makes a new profile.
 * `mode="add"` merges into the current profile, a newer rating winning over an older one.
 */
export function ImportForm({ mode = 'replace' }: { mode?: 'replace' | 'add' }) {
  const { profile, setProfile } = useProfile()
  const navigate = useNavigate()
  const fileInput = useRef<HTMLInputElement>(null)
  const [files, setFiles] = useState<File[]>([])
  const [username, setUsername] = useState('')
  const [keep, setKeep] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const adding = mode === 'add'

  const chooseFiles = (list: FileList | null) => {
    if (list?.length) {
      setFiles(Array.from(list))
      setError(null)
    }
  }
  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    chooseFiles(e.dataTransfer.files)
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    const name = username.trim()
    if (!files.length && !name) {
      setError('Choose your Letterboxd export, or type your username.')
      return
    }
    setBusy(true)
    try {
      let films: Film[]
      let unmatched = 0
      let source: Profile['source']
      if (files.length) {
        const rows = combineExport(await readExportFiles(files))
        const matched = await api.match(rows)
        films = matched.films.map((f) => ({
          tmdb_id: f.tmdb_id,
          media_type: f.media_type,
          rating: f.rating,
          rewatch: f.rewatch,
        }))
        unmatched = matched.unmatched.length
        source = 'export'
      } else {
        const imported = await api.importLetterboxd(name)
        films = imported.films.map((f) => ({
          tmdb_id: f.tmdb_id,
          media_type: f.media_type,
          rating: f.rating,
          rewatch: f.rewatch,
        }))
        unmatched = imported.films.filter((f) => !f.in_catalog).length
        source = 'username'
      }
      if (!films.length) throw new Error('No films found in that import.')

      let merged = films
      if (adding && profile) {
        const byId = new Map(profile.films.map((f) => [f.tmdb_id, f]))
        for (const f of films) byId.set(f.tmdb_id, f)
        merged = [...byId.values()]
      }

      let consentedAt = adding ? profile?.consentedAt : undefined
      let deletionToken = adding ? profile?.deletionToken : undefined
      if (keep) {
        const stored = await api.consent({
          source: source === 'export' ? 'letterboxd-export' : 'letterboxd-username',
          username: source === 'username' ? name : undefined,
          films: merged,
        })
        consentedAt = new Date().toISOString()
        deletionToken = stored.token
      }

      setProfile({
        name: (adding && profile?.name) || name || 'You',
        films: merged,
        source: adding && profile ? profile.source : source,
        username: source === 'username' ? name : profile?.username,
        importedAt: new Date().toISOString(),
        matched: merged.length,
        unmatched: (adding && profile ? profile.unmatched : 0) + unmatched,
        consentedAt,
        deletionToken,
        notForMe: adding && profile ? profile.notForMe : [],
      })
      navigate('/for-you')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'That import failed. Try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-6 lg:gap-7" noValidate>
      <div
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={`flex flex-col items-center gap-1 rounded-xl border-2 border-dashed px-4 py-6 text-center lg:px-6 lg:py-10 ${
          dragging ? 'border-accent' : 'border-field'
        }`}
      >
        <svg
          aria-hidden="true"
          width="34"
          height="34"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="mb-1 text-accent"
        >
          <path d="M12 16V4M7 9l5-5 5 5M4 20h16" />
        </svg>
        <div className="text-[19px] font-bold lg:text-[22px]">
          {files.length
            ? files.map((f) => f.name).join(', ')
            : adding
              ? 'Drop your Letterboxd export here'
              : 'Drop your Letterboxd export here'}
        </div>
        <div className="mb-3 text-[15px] text-muted lg:text-[17px]">
          ratings.csv, diary.csv or the whole .zip
        </div>
        <input
          ref={fileInput}
          type="file"
          accept=".zip,.csv"
          multiple
          className="sr-only"
          aria-label="Letterboxd export file"
          onChange={(e) => chooseFiles(e.target.files)}
        />
        <button
          type="button"
          onClick={() => fileInput.current?.click()}
          className="press min-h-12 cursor-pointer rounded-[10px] border-0 bg-surface2 px-6 py-3 text-[17px] font-bold text-ink"
        >
          Choose a file
        </button>
      </div>

      <div className="flex items-center gap-4 text-[15px] text-muted lg:text-base">
        <span className="h-px flex-1 bg-line" />
        or
        <span className="h-px flex-1 bg-line" />
      </div>

      <div className="flex flex-col gap-2.5">
        <label htmlFor="lb-user" className="text-base font-bold lg:text-[17px]">
          {adding ? 'Or fetch the latest entries for a username' : 'Your Letterboxd username'}
        </label>
        <input
          id="lb-user"
          type="text"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="for example VetOW"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          className="min-h-[52px] w-full rounded-[10px] border-[1.5px] border-field bg-bg px-4 text-lg text-ink lg:min-h-[54px] lg:px-[18px] lg:text-[19px]"
        />
        <div className="text-sm text-muted lg:text-base">
          A username only returns your latest 50 or so entries. An export brings your whole history.
        </div>
      </div>

      <div className="flex items-start gap-3.5">
        <input
          id="lb-keep"
          type="checkbox"
          checked={keep}
          onChange={(e) => setKeep(e.target.checked)}
          className="mt-[3px] h-[22px] w-[22px] flex-none accent-[var(--accent)]"
        />
        <label htmlFor="lb-keep" className="text-[15px] leading-[1.45] lg:text-[17px] lg:leading-[1.5]">
          Let PlotPoints keep my imported ratings to improve the project. I can ask to delete them at
          any time.
        </label>
      </div>

      {error && (
        <div role="alert" className="rounded-[10px] border border-field px-4 py-3 text-base">
          {error}
        </div>
      )}

      <button
        type="submit"
        disabled={busy}
        className="press min-h-[54px] w-full cursor-pointer rounded-xl border-0 bg-accent px-7 py-3.5 text-[19px] font-bold text-on disabled:cursor-wait disabled:opacity-70 lg:min-h-[58px] lg:text-xl"
      >
        {busy ? 'Reading your history…' : adding ? 'Add to my list' : 'Find my recommendations'}
      </button>
    </form>
  )
}
