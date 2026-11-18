import { useState, type ReactNode } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { currentTheme, toggleTheme, type Theme } from '../lib/theme'

const TABS: [string, string][] = [
  ['For you', '/for-you'],
  ['Franchises', '/franchises'],
  ['Streaming', '/streaming'],
  ['Import', '/import'],
]

export function Wordmark({ className = '' }: { className?: string }) {
  return (
    <div
      className={`text-center font-bold leading-none tracking-[0.01em] text-[34px] sm:text-[44px] lg:text-[52px] ${className}`}
    >
      <Link to="/" className="no-underline">
        Plot<span className="text-accent">Points</span>
      </Link>
    </div>
  )
}

function Nav() {
  return (
    <nav
      aria-label="Sections"
      className="flex flex-nowrap items-center justify-center overflow-x-auto whitespace-nowrap border-y border-line sm:flex-wrap sm:overflow-visible"
    >
      {TABS.map(([label, to], i) => (
        <span key={to} className="flex items-center">
          {i > 0 && (
            <span aria-hidden="true" className="mx-[11px] text-muted sm:mx-4 lg:mx-[22px]">
              /
            </span>
          )}
          <NavLink
            to={to}
            className={({ isActive }) =>
              `border-b-2 px-0.5 py-[13px] text-base font-bold no-underline sm:py-3 sm:text-[17px] lg:text-[18px] ${
                isActive ? 'border-accent text-accent' : 'border-transparent text-ink'
              }`
            }
          >
            {label}
          </NavLink>
        </span>
      ))}
    </nav>
  )
}

function Footer() {
  const [theme, setTheme] = useState<Theme>(currentTheme)
  return (
    <footer className="mt-10 flex flex-wrap justify-center gap-x-5 gap-y-1.5 border-t border-line pt-[22px] text-sm text-muted sm:mt-14 sm:gap-x-6 lg:mt-16 lg:gap-x-7 lg:pt-7 lg:text-[15px]">
      <Link to="/about">About and credits</Link>
      <Link to="/privacy">Privacy</Link>
      <Link to="/privacy#delete">Delete my data</Link>
      <button
        type="button"
        onClick={() => setTheme(toggleTheme())}
        className="cursor-pointer border-0 bg-transparent p-0 font-[inherit] text-[length:inherit] text-muted underline"
      >
        {theme === 'dark' ? 'Light mode' : 'Dark mode'}
      </button>
    </footer>
  )
}

/**
 * Placeholder for a 160x600 skyscraper ad. Swap the body for the ad network's tag when one is
 * chosen; the rail (size, stickiness, breakpoint) stays. Until then it doubles as the
 * "please disable your adblocker" card the site will show when an ad fails to load.
 */
function AdSlot({ side }: { side: 'left' | 'right' }) {
  // Width is all the margin beside the 1200px column (160px floor, 1272px = the 4K margin, where
  // ultrawide stops growing). Height is twice the width, capped at the viewport, 600px minimum.
  // Text is sized in container-width units so the card scales with it.
  return (
    <aside
      aria-label={`Sponsored (${side})`}
      className="@container sticky top-6 hidden [--w:clamp(160px,calc((100vw_-_1200px)/2_-_48px),1272px)] h-[max(600px,min(calc(var(--w)*2),calc(100vh_-_48px)))] w-(--w) shrink-0 self-start rounded-lg border border-dashed border-line bg-surface text-center min-[1400px]:block"
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
      <div className="flex min-h-screen w-full max-w-[1200px] flex-col px-4 pb-10 sm:px-8 lg:px-10 lg:pb-14 min-[1400px]:px-0 min-[1400px]:pt-0">
        <header className="pt-16 sm:pt-9 lg:pt-11 min-[1400px]:pt-5">
          <Wordmark className="pb-3.5 pt-1 sm:pb-5 lg:pb-6 lg:pt-2" />
          {nav && <Nav />}
        </header>
        <main className="flex-1">{children}</main>
        <Footer />
      </div>
      <AdSlot side="right" />
    </div>
  )
}
