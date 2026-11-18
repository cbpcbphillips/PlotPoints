import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { ImportForm } from '../components/ImportForm'
import { Shell } from '../components/Shell'
import { PageTitle } from '../components/States'
import { api } from '../lib/api'
import { prettyDate } from '../lib/format'
import { useProfile } from '../lib/profile'

/** `/` : the first visit. No navigation, one job. Returning visitors skip straight to their list. */
export function Landing() {
  const { profile } = useProfile()
  if (profile) return <Navigate to="/for-you" replace />
  return (
    <Shell nav={false}>
      <div className="mx-auto flex max-w-[720px] flex-col gap-7 pb-6 pt-9 lg:gap-9 lg:pb-10 lg:pt-[72px]">
        <div className="flex flex-col gap-2.5 text-center lg:gap-3.5">
          <h1 className="m-0 text-balance text-[34px] font-bold leading-[1.08] tracking-[-0.01em] sm:text-[44px] lg:text-[56px]">
            Bring your Letterboxd history
          </h1>
          <p className="m-0 text-balance text-[17px] text-muted lg:text-[21px]">
            PlotPoints compares what you rate highly with 23,747 films and ranks the ones you have
            not seen.
          </p>
        </div>
        <div className="rounded-2xl bg-surface p-5 sm:p-8 lg:rounded-[14px] lg:p-9">
          <ImportForm />
        </div>
        <p className="m-0 text-center text-[15px] text-muted lg:text-[17px]">
          Not sure how to export? In Letterboxd, open Settings, then Import &amp; Export, then Export
          Your Data.
        </p>
      </div>
    </Shell>
  )
}

/** `/import` : the returning visitor's view of what is loaded, with switch-user and deletion. */
export function ImportReturning() {
  const { profile, setProfile } = useProfile()
  const navigate = useNavigate()
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  if (!profile) return <Navigate to="/" replace />

  const rated = profile.films.filter((f) => f.rating != null).length

  async function deleteStored() {
    if (!profile?.deletionToken) return
    setBusy(true)
    setNote(null)
    try {
      await api.deleteData(profile.deletionToken)
      setProfile({ ...profile, consentedAt: undefined, deletionToken: undefined })
      setNote('Your stored ratings will be removed the next time the pipeline runs.')
    } catch (err) {
      setNote(err instanceof Error ? err.message : 'That did not go through. Try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Shell>
      <PageTitle title="Your history">
        The more films you rate, the sharper the matches. Add an export any time, or start over as
        someone else.
      </PageTitle>

      <section className="flex flex-wrap items-stretch gap-6 pt-8 lg:gap-7 lg:pt-9">
        <div className="flex min-w-0 flex-[1_1_380px] flex-col gap-5 rounded-[14px] bg-surface p-6 lg:p-10">
          <div className="text-[15px] font-bold uppercase tracking-[0.16em] text-muted">
            Current profile
          </div>
          <div className="text-[34px] font-bold leading-[1.05] tracking-[-0.01em] lg:text-5xl">
            {profile.name}
          </div>
          <div className="text-[56px] font-bold leading-none tabular-nums text-accent lg:text-[76px]">
            {profile.matched.toLocaleString()} films
          </div>
          <div className="-mt-2.5 text-[17px] text-muted lg:text-[19px]">
            {rated.toLocaleString()} rated
            {profile.unmatched > 0 && ` · ${profile.unmatched.toLocaleString()} not in the catalog`}
            {' · imported '}
            {prettyDate(profile.importedAt)}
          </div>
          {profile.source === 'username' && (
            <p className="m-0 text-base text-muted lg:text-lg">
              Imported from a username, so only your latest entries are included. An export would
              add the rest of your history.
            </p>
          )}
          <div className="mt-auto flex flex-wrap gap-3 pt-2">
            <button
              type="button"
              onClick={() => {
                setProfile(null)
                navigate('/')
              }}
              className="press min-h-[52px] cursor-pointer rounded-xl border-0 bg-accent px-7 py-3.5 text-lg font-bold text-on lg:min-h-14 lg:text-[19px]"
            >
              Switch user
            </button>
            <Link
              to="/for-you"
              className="press inline-flex min-h-[52px] items-center rounded-xl bg-surface2 px-7 text-lg font-bold text-ink no-underline lg:min-h-14 lg:text-[19px]"
            >
              Back to my list
            </Link>
          </div>
        </div>

        <div className="flex min-w-0 flex-[1_1_380px] flex-col gap-5 rounded-[14px] bg-surface p-6 lg:p-10">
          <div className="text-[15px] font-bold uppercase tracking-[0.16em] text-muted">
            Add more history
          </div>
          <ImportForm mode="add" />
        </div>
      </section>

      <section
        id="consent"
        className="mt-7 flex flex-wrap items-center justify-between gap-5 rounded-[14px] bg-surface p-6 lg:px-10 lg:py-8"
      >
        <p className="m-0 min-w-0 flex-[1_1_380px] text-base lg:text-lg">
          {profile.consentedAt
            ? `PlotPoints keeps my imported ratings to improve the project. I agreed on ${prettyDate(
                profile.consentedAt,
              )} and can delete them at any time.`
            : 'Your ratings stay on this device. Nothing about you is stored by PlotPoints.'}
        </p>
        {profile.deletionToken && (
          <button
            type="button"
            disabled={busy}
            onClick={deleteStored}
            className="press min-h-[52px] cursor-pointer rounded-xl border-2 border-line bg-transparent px-6 py-3 text-lg font-bold text-ink disabled:opacity-60"
          >
            Delete my data
          </button>
        )}
        {note && (
          <p role="status" className="m-0 basis-full text-base text-muted">
            {note}
          </p>
        )}
      </section>
    </Shell>
  )
}
