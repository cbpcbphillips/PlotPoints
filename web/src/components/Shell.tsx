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

/** Page frame. `nav={false}` is the first-visit import screen, which has no navigation. */
export function Shell({ children, nav = true }: { children: ReactNode; nav?: boolean }) {
  return (
    <div className="mx-auto flex min-h-screen max-w-[1200px] flex-col px-4 pb-10 sm:px-8 lg:px-10 lg:pb-14">
      <header className="pt-16 sm:pt-9 lg:pt-11">
        <Wordmark className="pb-3.5 pt-1 sm:pb-5 lg:pb-6 lg:pt-2" />
        {nav && <Nav />}
      </header>
      <main className="flex-1">{children}</main>
      <Footer />
    </div>
  )
}
