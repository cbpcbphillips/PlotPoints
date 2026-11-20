import { useEffect, useState, type ReactNode } from 'react'

/** How long a wait is normal before we say the server is probably just waking up. */
const SLOW_MS = 3500

export function Loading({ what = 'your list' }: { what?: string }) {
  const [slow, setSlow] = useState(false)
  useEffect(() => {
    const t = window.setTimeout(() => setSlow(true), SLOW_MS)
    return () => window.clearTimeout(t)
  }, [])
  return (
    <div role="status" className="py-24 text-center text-lg text-muted">
      Finding {what}…
      {slow && (
        <p className="m-0 mt-3 text-base">
          Waking up the server. The first visit after a quiet spell takes a few seconds.
        </p>
      )}
    </div>
  )
}

export function ErrorNote({ error, retry }: { error: unknown; retry?: () => void }) {
  const message = error instanceof Error ? error.message : 'Something went wrong.'
  return (
    <div role="alert" className="mx-auto max-w-xl py-20 text-center">
      <p className="m-0 text-xl">{message}</p>
      {retry && (
        <button
          type="button"
          onClick={retry}
          className="press mt-6 cursor-pointer rounded-xl border-0 bg-surface2 px-8 py-3 text-lg font-bold text-ink"
        >
          Try again
        </button>
      )}
    </div>
  )
}

export function PageTitle({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <section className="pagehead">
      <h1>{title}</h1>
      {children && <p className="m-0 max-w-[62ch] text-base text-muted">{children}</p>}
    </section>
  )
}
