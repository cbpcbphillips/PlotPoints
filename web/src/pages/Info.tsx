import { useQuery } from '@tanstack/react-query'
import { useEffect, useState, type ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { Shell, TmdbMark } from '../components/Shell'
import { PageTitle } from '../components/States'
import { api } from '../lib/api'
import { ANALYTICS_ON } from '../lib/env'
import { prettyDate } from '../lib/format'
import { useProfile } from '../lib/profile'

function Block({ title, id, children }: { title: string; id?: string; children: ReactNode }) {
  return (
    <section id={id} className="border-t border-line py-8 lg:py-10">
      <h2 className="m-0 mb-3 text-2xl font-bold lg:text-[1.875rem]">{title}</h2>
      <div className="flex max-w-[44em] flex-col gap-3 text-[1.0625rem] text-muted lg:text-lg">
        {children}
      </div>
    </section>
  )
}

export function About() {
  const meta = useQuery({ queryKey: ['meta'], queryFn: api.meta, staleTime: Infinity })
  return (
    <Shell title="About and credits" ads={false}>
      <PageTitle title="About and credits">
        A film recommender built to learn how recommendation systems work, end to end.
      </PageTitle>

      <Block title="How it works">
        <p className="m-0">
          Every film in the catalog is turned into a vector of numbers by an embedding model, from
          its cast, director, genres, keywords and plot. Films that are alike land close together.
          Your ratings pick out the films you loved, and each film you have not seen is scored by
          how close it sits to them.
        </p>
        <p className="m-0">
          The catalog holds {meta.data ? meta.data.titles.toLocaleString() : 'about 23,700'} films
          with at least 100 votes on TMDB. Films shorter than an hour are left out of the
          recommendations, and a film is nudged down if its TMDB rating is below the standard of the
          films you like.
        </p>
      </Block>

      <Block title="What the numbers mean">
        <p className="m-0">
          <b>Score</b> is what the list is ordered by. Each film you rated highly is compared with
          every candidate, corrected for films that are close to everything, and weighted by how
          much you liked it. It is not a percentage: the best picks sit around 2 to 4.
        </p>
        <p className="m-0">
          <b>Match</b> is the cosine similarity between a recommendation and the films that explain
          it, averaged and shown as a percentage. 100% would be a film identical to the ones you
          rated highly; unrelated films sit around 30 to 40%, so 60% is a strong match. Because the
          list is ordered by score, match is not strictly decreasing down it, and that is expected.
        </p>
        <p className="m-0">
          <b>Novelty</b> is 100 minus the similarity to the single film that explains a pick best,
          so a higher number means the pick is further from anything you have already rated.{' '}
          <b>TMDB</b> is the film&rsquo;s public rating out of 10.
        </p>
      </Block>

      <Block title="Credits">
        <p className="m-0">
          <TmdbMark className="mb-2 h-5 w-auto" />
        </p>
        <p className="m-0">
          This product uses the TMDB API but is not endorsed or certified by TMDB. Film metadata,
          images and ratings come from{' '}
          <a
            href="https://www.themoviedb.org"
            target="_blank"
            rel="noreferrer"
            className="underline"
          >
            The Movie Database
          </a>
          .
        </p>
        <p className="m-0">
          Streaming availability comes from{' '}
          <a
            href="https://www.justwatch.com"
            target="_blank"
            rel="noreferrer"
            className="underline"
          >
            JustWatch
          </a>
          , for the United States only
          {meta.data && `, as of ${prettyDate(meta.data.providers_as_of)}`}. It changes often; check
          the service before you plan an evening around it.
        </p>
        <p className="m-0">
          Letterboxd is a trademark of its owner. PlotPoints is not affiliated with Letterboxd.
        </p>
      </Block>
    </Shell>
  )
}

export function Privacy() {
  const { profile, setProfile } = useProfile()
  const { hash } = useLocation()
  const [token, setToken] = useState('')
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (hash) document.getElementById(hash.slice(1))?.scrollIntoView({ behavior: 'smooth' })
  }, [hash])

  async function remove(t: string) {
    setBusy(true)
    setStatus(null)
    try {
      await api.deleteData(t.trim())
      if (profile?.deletionToken === t.trim()) {
        setProfile({ ...profile, consentedAt: undefined, deletionToken: undefined })
      }
      setToken('')
      setStatus({
        ok: true,
        text: 'Done. Your stored ratings will be removed the next time the pipeline runs.',
      })
    } catch (err) {
      setStatus({
        ok: false,
        text: err instanceof Error ? err.message : 'That did not go through.',
      })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Shell title="Privacy" ads={false}>
      <PageTitle title="Privacy" />
      <Block title="What stays on your device">
        <p className="m-0">
          PlotPoints has no accounts. Your Letterboxd export is read in your browser, and your films
          and ratings are kept in this browser&rsquo;s storage so your list is still here next
          visit. To make a recommendation, the films you have seen and their ratings are sent to the
          server, used to compute your list, and not kept.
        </p>
      </Block>
      <Block title="What the server logs">
        <p className="m-0">
          For each request the server notes the kind of page asked for, whether it worked and how
          long it took, and for a few actions an anonymous count: that a list was made for one or
          several people, which kinds of filter were used, a rough size for a history (for example
          &ldquo;15 to 49 films&rdquo;), and that an import, a kept copy or a deletion happened. It
          never logs film titles or ids, ratings, names, usernames, deletion tokens or addresses, so
          the log cannot say who did anything. It is used to see whether PlotPoints is useful and
          whether it is running well.
        </p>
      </Block>
      {ANALYTICS_ON && (
        <Block title="Visit counts">
          <p className="m-0">
            Visits are counted with Cloudflare Web Analytics. It sets no cookies and does not follow
            you from site to site; it sees which page was opened, the country and the kind of
            device, not who you are.
          </p>
        </Block>
      )}
      <Block title="Watching together">
        <p className="m-0">
          If you add other people to a group, their films and ratings are kept in this browser too,
          next to yours, and sent to the server only to rank that one list. They are never stored on
          the server, and the consent box above covers only your own history. Only add people who
          are happy for you to use their ratings; you can remove them, or everyone, at any time from
          the Together page.
        </p>
      </Block>
      <Block title="What is stored, unless you opt out">
        <p className="m-0">
          When you import, the box that lets PlotPoints keep a copy of your film list is ticked for
          you. Untick it and nothing is kept. If you leave it ticked, PlotPoints keeps a TMDB id,
          your rating and whether it was a rewatch for each film, to improve the project. It is
          anonymous: your Letterboxd username and your name are never sent with it, so the copy
          cannot be tied back to you. Your reviews, tags and the file itself are never sent.
        </p>
        <p className="m-0">
          Keeping a copy gives you a deletion token, kept in this browser. It is the only way to
          delete what was stored, because there is no account to sign in to, so clearing this
          browser&rsquo;s data without deleting first means the copy can no longer be removed.
        </p>
      </Block>
      <Block title="Delete my data" id="delete">
        {profile?.deletionToken ? (
          <div className="flex flex-wrap items-center gap-4">
            <p className="m-0 flex-[1_1_320px]">
              You agreed to keep your ratings on {prettyDate(profile.consentedAt ?? '')}.
            </p>
            <button
              type="button"
              disabled={busy}
              onClick={() => remove(profile.deletionToken!)}
              className="press min-h-[52px] cursor-pointer rounded-xl border-0 bg-accent px-7 py-3 text-lg font-bold text-on disabled:opacity-60"
            >
              Delete my stored ratings
            </button>
          </div>
        ) : (
          <p className="m-0">
            Nothing of yours is stored. If you saved a token elsewhere, use it here:
          </p>
        )}
        <form
          className="flex flex-wrap gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            if (token.trim()) void remove(token)
          }}
        >
          <label htmlFor="del-token" className="w-full text-base font-bold">
            Deletion token
          </label>
          <input
            id="del-token"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="Deletion token"
            autoComplete="off"
            spellCheck={false}
            className="min-h-[52px] min-w-0 flex-[1_1_280px] rounded-[10px] border-[1.5px] border-field bg-bg px-4 text-lg text-ink"
          />
          <button
            type="submit"
            disabled={busy || !token.trim()}
            className="press min-h-[52px] cursor-pointer rounded-xl border-0 bg-surface2 px-7 text-lg font-bold text-ink disabled:opacity-60"
          >
            Delete with token
          </button>
        </form>
        {status && (
          <p role="status" className={`m-0 ${status.ok ? '' : 'text-ink'}`}>
            {status.text}
          </p>
        )}
      </Block>
    </Shell>
  )
}
