import { toneOf } from '../lib/format'

/**
 * The title-on-color tile chosen on the design canvas. It carries the title as text so the page
 * reads the same with images off; real posters can slot in here later without touching callers.
 */
export function Tile({
  id,
  title,
  className = '',
}: {
  id: number
  title: string
  className?: string
}) {
  return (
    <div
      aria-hidden="true"
      className={`tone-${toneOf(id)} box-border flex items-end overflow-hidden font-bold leading-[1.05] ${className}`}
    >
      {title}
    </div>
  )
}

/** The big percentage, the one number the design leads with. */
export function Match({
  value,
  size = 'text-[46px]',
  label = true,
}: {
  value: number
  size?: string
  label?: boolean
}) {
  return (
    <div className="flex items-baseline gap-2">
      <span className={`${size} font-bold leading-none tabular-nums text-accent`}>{value}%</span>
      {label && (
        <span className="text-[12px] font-bold uppercase tracking-[0.14em] text-muted lg:text-[13px]">
          match
        </span>
      )}
    </div>
  )
}
