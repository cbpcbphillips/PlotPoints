// Apply display settings before first paint so nobody sees a flash of the wrong theme or
// text size. Mirrors applySettings() in src/lib/settings.ts (which also loads the reading font).
// A separate file, not an inline script, so the Content-Security-Policy can forbid inline scripts.
try {
  var d = document.documentElement
  var s = JSON.parse(localStorage.getItem('pp-settings') || 'null')
  if (!s) {
    var t = localStorage.getItem('pp-theme') // the old light/dark toggle
    if (t === 'light' || t === 'dark') s = { theme: t }
  }
  s = s || {}
  if (s.theme === 'light' || s.theme === 'dark') d.setAttribute('data-theme', s.theme)
  var more =
    s.contrast === 'high' ||
    (s.contrast !== 'standard' && window.matchMedia('(prefers-contrast: more)').matches)
  if (more) d.setAttribute('data-contrast', 'more')
  if (s.dyslexia === true) d.setAttribute('data-reading', 'dyslexia')
  if (s.motion === 'reduce') d.setAttribute('data-motion', 'reduce')
  if (s.textScale > 100 && s.textScale <= 150) d.style.fontSize = s.textScale + '%'
} catch (e) {}
