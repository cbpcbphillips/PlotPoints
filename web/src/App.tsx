import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { BrowserRouter, Route, Routes, useLocation } from 'react-router-dom'
import { Browse } from './pages/Browse'
import { BrowseFacet } from './pages/BrowseFacet'
import { Film } from './pages/Film'
import { Franchises } from './pages/Franchises'
import { ForYou } from './pages/ForYou'
import { Landing, ImportReturning } from './pages/Import'
import { About, Privacy } from './pages/Info'
import { Settings } from './pages/Settings'
import { Streaming } from './pages/Streaming'
import { Together } from './pages/Together'
import { GroupProvider } from './lib/group'
import { ProfileProvider } from './lib/profile'

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 5 * 60_000, retry: 1, refetchOnWindowFocus: false } },
})

/**
 * On a route change: back to the top, and keyboard focus to the page's heading (or the content
 * area), so keyboard and screen-reader users start at the new page and not wherever the old link
 * was (WCAG 2.4.3). Not on the first load, which already starts at the top of the document.
 */
function RouteChange() {
  const { pathname, hash } = useLocation()
  const first = useRef(true)
  useEffect(() => {
    if (!hash) window.scrollTo(0, 0)
    if (first.current) {
      first.current = false
      return
    }
    if (hash) return
    const target = document.querySelector<HTMLElement>('main h1, main')
    if (target) {
      target.setAttribute('tabindex', '-1')
      target.focus({ preventScroll: true })
    }
  }, [pathname, hash])
  return null
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ProfileProvider>
        <GroupProvider>
          <BrowserRouter>
            <RouteChange />
            <Routes>
              <Route path="/" element={<Landing />} />
              <Route path="/for-you" element={<ForYou />} />
              <Route path="/franchises" element={<Franchises />} />
              <Route path="/streaming" element={<Streaming />} />
              <Route path="/together" element={<Together />} />
              <Route path="/browse" element={<Browse />} />
              <Route path="/browse/:kind/:value" element={<BrowseFacet />} />
              <Route path="/film/:tmdbId" element={<Film />} />
              <Route path="/import" element={<ImportReturning />} />
              <Route path="/about" element={<About />} />
              <Route path="/privacy" element={<Privacy />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="*" element={<Landing />} />
            </Routes>
          </BrowserRouter>
        </GroupProvider>
      </ProfileProvider>
    </QueryClientProvider>
  )
}
