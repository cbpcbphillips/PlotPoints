import { useEffect, type ReactNode } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { resolvedTheme, toggleTheme, useSettings } from '../lib/settings'

const TABS: [string, string][] = [
  ['For you', '/for-you'],
  ['Franchises', '/franchises'],
  ['Browse', '/browse'],
  ['Streaming', '/streaming'],
  ['Together', '/together'],
  ['Import', '/import'],
  ['Settings', '/settings'],
]

function ThemeButton() {
  const settings = useSettings()
  const dark = resolvedTheme(settings) === 'dark'
  return (
    <button
      type="button"
      className="btn ghost"
      onClick={toggleTheme}
      aria-label={dark ? 'Switch to light theme' : 'Switch to dark theme'}
    >
      <span aria-hidden="true">◐</span> {dark ? 'Dark' : 'Light'}
    </button>
  )
}

/**
 * Sticky, translucent top bar: brand, the sections, the theme switch. It sits in the page
 * column so its contents line up with the page, while its background and bottom rule are drawn
 * across the whole window by `.top::before` (see index.css).
 */
function TopBar({ nav }: { nav: boolean }) {
  return (
    <header className="top">
      <div className="bar">
        <Link to="/" className="brand">
          Plot<b>Points</b>
        </Link>
        {nav && (
          <nav aria-label="Sections" className="navlinks flex gap-0.5">
            {TABS.map(([label, to]) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) => `navlink${isActive ? ' on' : ''}`}
              >
                {label}
              </NavLink>
            ))}
          </nav>
        )}
        <ThemeButton />
      </div>
    </header>
  )
}

function Footer() {
  return (
    <footer className="mt-10 flex flex-wrap justify-center gap-x-5 gap-y-1.5 border-t border-line pt-[22px] text-sm text-muted sm:mt-14 sm:gap-x-6 lg:mt-16 lg:gap-x-7 lg:pt-7 lg:text-[0.9375rem]">
      <Link to="/about">About and credits</Link>
      <Link to="/settings">Display settings</Link>
      <Link to="/privacy">Privacy</Link>
      <Link to="/privacy#delete">Delete my data</Link>
    </footer>
  )
}

/**
 * Where an ad goes. There is no ad network yet; each slot reserves its space (so nothing shifts
 * when one loads) and shows a neutral placeholder. Swap the body for the network's tag later;
 * the placement rules stay:
 *   rail        1680px and up: both sides, 160-300px wide, sticky. 1400-1679px: right side only.
 *   leaderboard 728-1399px: 728x90, in the page flow under the main heading or hero.
 *   infeed      under 728px: 300x250, between two rows of content, never above the first screen.
 * Network requirements to carry into the contract: no autoplay audio or video, nothing moving for
 * more than 5 seconds without a pause control (WCAG 2.2.2), no focus traps, and a visible
 * "Advertisement" label. Pages that carry personal data or settings opt out (`ads={false}`).
 */
type AdKind = 'rail-left' | 'rail-right' | 'leaderboard' | 'infeed'

const AD_VISIBILITY: Record<AdKind, string> = {
  'rail-left': 'hidden min-[1680px]:block',
  'rail-right': 'hidden min-[1400px]:block',
  leaderboard: 'hidden min-[728px]:max-[1399px]:block',
  infeed: 'block min-[728px]:hidden',
}

export function Ad({ kind }: { kind: AdKind }) {
  const rail = kind.startsWith('rail')
  return (
    <aside
      aria-label="Advertisement"
      data-ad={kind}
      className={
        rail
          ? // The width is the margin beside the 1240px column: 160px floor, 300px cap (half-page ad).
            // Height is twice the width, capped at the screen below the sticky bar, 600px minimum.
            `@container mt-(--rail-top) sticky top-(--rail-top) [--w:clamp(160px,calc((100vw_-_1240px)/2_-_48px),300px)] h-[max(600px,min(calc(var(--w)*2),calc(100vh_-_var(--rail-top)_-_24px)))] w-(--w) shrink-0 self-start ${AD_VISIBILITY[kind]}`
          : `mx-auto my-6 w-full ${kind === 'leaderboard' ? 'h-[90px] max-w-[728px]' : 'h-[250px] max-w-[300px]'} ${AD_VISIBILITY[kind]}`
      }
    >
      <div className="flex h-full flex-col items-center justify-center rounded-lg border border-dashed border-line-strong bg-surface text-center">
        <span className="text-xs font-bold uppercase tracking-[0.08em] text-muted">
          Advertisement
        </span>
      </div>
    </aside>
  )
}

/** Sets the tab title ("For you · PlotPoints"); screen readers announce it on navigation. */
function useDocumentTitle(title?: string) {
  useEffect(() => {
    document.title = title ? `${title} · PlotPoints` : 'PlotPoints'
  }, [title])
}

/**
 * Page frame. `nav={false}` is the first-visit import screen, which has no navigation. The ad
 * rails sit outside the 1240px column (see Ad); `ads={false}` leaves them out.
 */
export function Shell({
  children,
  nav = true,
  ads = true,
  title,
}: {
  children: ReactNode
  nav?: boolean
  ads?: boolean
  title?: string
}) {
  useDocumentTitle(title)
  return (
    <div className="flex justify-center gap-6 overflow-x-clip pt-0 min-[1400px]:px-3">
      <a href="#main" className="skip">
        Skip to content
      </a>
      {ads && <Ad kind="rail-left" />}
      <div className="zoomcol flex w-full max-w-[1240px] flex-col px-5 pb-28 sm:px-8 min-[1400px]:px-0">
        <TopBar nav={nav} />
        <main id="main" tabIndex={-1} className="flex-1 outline-none">
          {children}
        </main>
        <Footer />
      </div>
      {ads && <Ad kind="rail-right" />}
    </div>
  )
}
