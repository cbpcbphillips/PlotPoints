import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useEffect } from 'react'
import { BrowserRouter, Route, Routes, useLocation } from 'react-router-dom'
import { Film } from './pages/Film'
import { Franchises } from './pages/Franchises'
import { ForYou } from './pages/ForYou'
import { Landing, ImportReturning } from './pages/Import'
import { About, Privacy } from './pages/Info'
import { Streaming } from './pages/Streaming'
import { ProfileProvider } from './lib/profile'

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 5 * 60_000, retry: 1, refetchOnWindowFocus: false } },
})

function ScrollToTop() {
  const { pathname, hash } = useLocation()
  useEffect(() => {
    if (!hash) window.scrollTo(0, 0)
  }, [pathname, hash])
  return null
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ProfileProvider>
        <BrowserRouter>
          <ScrollToTop />
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/for-you" element={<ForYou />} />
            <Route path="/franchises" element={<Franchises />} />
            <Route path="/streaming" element={<Streaming />} />
            <Route path="/film/:tmdbId" element={<Film />} />
            <Route path="/import" element={<ImportReturning />} />
            <Route path="/about" element={<About />} />
            <Route path="/privacy" element={<Privacy />} />
            <Route path="*" element={<Landing />} />
          </Routes>
        </BrowserRouter>
      </ProfileProvider>
    </QueryClientProvider>
  )
}
