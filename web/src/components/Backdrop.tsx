import { useState } from 'react'
import { tmdbImage } from './Poster'

/** Decorative constellation behind the hero. Purely visual, so it is hidden from assistive tech. */
export function Backdrop({ path }: { path: string | null }) {
  const [failed, setFailed] = useState(false)
  if (path && !failed) {
    return (
      <div className="backdrop" aria-hidden="true">
        <img src={tmdbImage(path, 'w1280')} alt="" decoding="async" onError={() => setFailed(true)} />
      </div>
    )
  }
  return (
    <div className="backdrop" aria-hidden="true">
      <svg viewBox="0 0 800 335" preserveAspectRatio="xMidYMid slice">
        <g fill="#8FA0FF">
          <circle cx="90" cy="70" r="3" />
          <circle cx="210" cy="140" r="4" />
          <circle cx="330" cy="60" r="3" />
          <circle cx="420" cy="190" r="5" />
          <circle cx="520" cy="95" r="3" />
          <circle cx="640" cy="160" r="4" />
          <circle cx="730" cy="60" r="3" />
          <circle cx="150" cy="250" r="3" />
          <circle cx="560" cy="270" r="4" />
        </g>
        <g stroke="#F5B84B" strokeOpacity=".4" fill="none">
          <path d="M90 70L210 140M210 140L420 190M420 190L640 160M330 60L420 190M420 190L560 270" />
        </g>
        <circle cx="640" cy="160" r="10" fill="#F5B84B" />
        <circle cx="640" cy="160" r="17" fill="none" stroke="#F5B84B" />
      </svg>
    </div>
  )
}
