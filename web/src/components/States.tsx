import type { ReactNode } from 'react'

export function Loading({ what = 'your list' }: { what?: string }) {
  return (
    <div role="status" className="py-24 text-center text-xl text-muted">
      Finding {what}…
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
    <section className="flex flex-col gap-3 pb-3 pt-10 sm:pt-14 lg:pt-20">
      <h1 className="m-0 text-[34px] font-bold leading-[1.05] tracking-[-0.02em] sm:text-[44px] lg:text-[60px]">
        {title}
      </h1>
      {children && (
        <p className="m-0 max-w-[36em] text-lg text-muted lg:text-[22px]">{children}</p>
      )}
    </section>
  )
}
