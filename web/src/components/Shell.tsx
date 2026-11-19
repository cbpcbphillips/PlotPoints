import { useState, type ReactNode } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { currentTheme, toggleTheme, type Theme } from '../lib/theme'

const TABS: [string, string][] = [
  ['For you', '/for-you'],
  ['Franchises', '/franchises'],
  ['Streaming', '/streaming'],
  ['Import', '/import'],
]

function ThemeButton() {
  const [theme, setTheme] = useState<Theme>(currentTheme)
  return (
    <button type="button" className="btn ghost" onClick={() => setTheme(toggleTheme())}>
      ◐ {theme === 'dark' ? 'Dark' : 'Light'}
    </button>
  )
}

/** Sticky, translucent top bar: brand, the four sections, the theme switch. */
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
    <footer className="mt-10 flex flex-wrap justify-center gap-x-5 gap-y-1.5 border-t border-line pt-[22px] text-sm text-muted sm:mt-14 sm:gap-x-6 lg:mt-16 lg:gap-x-7 lg:pt-7 lg:text-[15px]">
      <Link to="/about">About and credits</Link>
      <Link to="/privacy">Privacy</Link>
      <Link to="/privacy#delete">Delete my data</Link>
    </footer>
  )
}

/**
 * Placeholder for a 160x600 skyscraper ad. Swap the body for the ad network's tag when one is
 * chosen; the rail (size, stickiness, breakpoint) stays. Until then it doubles as the
 * "please disable your adblocker" card the site will show when an ad fails to load.
 */
function AdSlot({ side }: { side: 'left' | 'right' }) {
  // Width is the margin beside the 1240px column, from a 160px floor up to a 300px cap (the
  // standard half-page ad). Beyond that the content scales up instead (.zoomcol in index.css).
  // Height is twice the width, capped at the viewport, 600px minimum. Text is sized in
  // container-width units so the card scales with it.
  return (
    <aside
      aria-label={`Sponsored (${side})`}
      className="@container sticky top-6 hidden [--w:clamp(160px,calc((100vw_-_1240px)/2_-_48px),300px)] h-[max(600px,min(calc(var(--w)*2),calc(100vh_-_48px)))] w-(--w) shrink-0 self-start rounded-lg border border-dashed border-line bg-surface text-center min-[1400px]:block"
    >
      <div className="flex h-full flex-col items-center justify-center gap-[6cqw] px-[10cqw] text-center">
        <span className="text-[clamp(11px,5cqw,64px)] font-bold uppercase tracking-[0.14em] text-muted">
          Advertisement
        </span>
        <p className="m-0 text-[clamp(15px,9cqw,120px)] font-bold leading-snug text-ink">
          Please disable your adblocker so we can keep Plot
          <span className="text-accent">Points</span> free for all.
        </p>
        <p className="m-0 text-[clamp(13px,6.5cqw,86px)] leading-snug text-muted">
          Ads are the only thing that pays for the servers.
        </p>
      </div>
    </aside>
  )
}

/**
 * Page frame. `nav={false}` is the first-visit import screen, which has no navigation. The ad
 * rails sit outside the 1200px column and only appear at 1400px and up; the column shrinks from 1200 toward ~1030 to make room
 * (2 x 160 + gaps), keeping lg-size layout.
 */
export function Shell({ children, nav = true }: { children: ReactNode; nav?: boolean }) {
  return (
    <div className="flex justify-center gap-6 pt-0 min-[1400px]:px-3 min-[1400px]:pt-6">
      <AdSlot side="left" />
      <div className="zoomcol flex w-full max-w-[1240px] flex-col px-5 pb-28 sm:px-8 min-[1400px]:px-0">
        <TopBar nav={nav} />
        <main className="flex-1">{children}</main>
        <Footer />
      </div>
      <AdSlot side="right" />
    </div>
  )
}
