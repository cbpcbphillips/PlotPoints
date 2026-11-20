import { useSyncExternalStore } from 'react'

/**
 * Display and accessibility preferences. Stored in this browser only (key `pp-settings`) and
 * applied as attributes on <html>, so the stylesheet does the rest. index.html runs the same
 * mapping before first paint so nobody sees a flash of the wrong theme.
 */
export type Theme = 'system' | 'light' | 'dark'
export type Contrast = 'system' | 'standard' | 'high'
export type Motion = 'system' | 'reduce'

export interface Settings {
  theme: Theme
  contrast: Contrast
  /** root font size as a percent of the browser default */
  textScale: number
  dyslexia: boolean
  motion: Motion
}

export const TEXT_SCALES = [100, 112.5, 125, 150] as const

export const DEFAULTS: Settings = {
  theme: 'system',
  contrast: 'system',
  textScale: 100,
  dyslexia: false,
  motion: 'system',
}

const KEY = 'pp-settings'
const LEGACY_THEME_KEY = 'pp-theme' // the old light/dark toggle, kept working

const oneOf = <T extends string>(v: unknown, ok: readonly T[], fallback: T): T =>
  ok.includes(v as T) ? (v as T) : fallback

/** Whatever is stored, coerced to a valid Settings (unknown or hand-edited values fall back). */
export function sanitize(raw: unknown): Settings {
  const r = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>
  const scale = Number(r.textScale)
  return {
    theme: oneOf(r.theme, ['system', 'light', 'dark'], DEFAULTS.theme),
    contrast: oneOf(r.contrast, ['system', 'standard', 'high'], DEFAULTS.contrast),
    textScale: TEXT_SCALES.includes(scale as (typeof TEXT_SCALES)[number])
      ? scale
      : DEFAULTS.textScale,
    dyslexia: r.dyslexia === true,
    motion: oneOf(r.motion, ['system', 'reduce'], DEFAULTS.motion),
  }
}

export function readSettings(): Settings {
  try {
    const raw = localStorage.getItem(KEY)
    if (raw) return sanitize(JSON.parse(raw))
    const legacy = localStorage.getItem(LEGACY_THEME_KEY)
    if (legacy === 'light' || legacy === 'dark') return { ...DEFAULTS, theme: legacy }
  } catch {
    /* blocked storage or bad JSON: use the defaults */
  }
  return { ...DEFAULTS }
}

/** Set or clear one attribute. */
function attr(root: HTMLElement, name: string, value: string | null) {
  if (value == null) root.removeAttribute(name)
  else root.setAttribute(name, value)
}

let fontLoaded = false

/** Put the settings on the document. Safe to call repeatedly. */
export function applySettings(s: Settings, root: HTMLElement = document.documentElement) {
  attr(root, 'data-theme', s.theme === 'system' ? null : s.theme)
  const wantsMore =
    s.contrast === 'high' ||
    (s.contrast === 'system' && window.matchMedia?.('(prefers-contrast: more)').matches)
  attr(root, 'data-contrast', wantsMore ? 'more' : null)
  attr(root, 'data-reading', s.dyslexia ? 'dyslexia' : null)
  attr(root, 'data-motion', s.motion === 'reduce' ? 'reduce' : null)
  root.style.fontSize = s.textScale === 100 ? '' : `${s.textScale}%`
  if (s.dyslexia && !fontLoaded) {
    fontLoaded = true // load the reading font only for people who ask for it
    void import('@fontsource/atkinson-hyperlegible/400.css')
    void import('@fontsource/atkinson-hyperlegible/700.css')
  }
}

// ---- a tiny store, so the top bar toggle and the Settings page stay in step

let current: Settings = readSettings()
const listeners = new Set<() => void>()

export function getSettings(): Settings {
  return current
}

export function updateSettings(patch: Partial<Settings>) {
  current = sanitize({ ...current, ...patch })
  try {
    localStorage.setItem(KEY, JSON.stringify(current))
  } catch {
    /* the choice just will not persist */
  }
  applySettings(current)
  listeners.forEach((l) => l())
}

export function resetSettings() {
  updateSettings({ ...DEFAULTS })
}

export function useSettings(): Settings {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb)
      return () => listeners.delete(cb)
    },
    getSettings,
    getSettings,
  )
}

/** The theme actually in force, resolving "system" against the OS setting. */
export function resolvedTheme(s: Settings = current): 'light' | 'dark' {
  if (s.theme !== 'system') return s.theme
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

/** The quick toggle in the top bar: flips light and dark and leaves everything else alone. */
export function toggleTheme() {
  updateSettings({ theme: resolvedTheme() === 'dark' ? 'light' : 'dark' })
}

/** Apply stored settings at startup (also re-checks "system" contrast when the OS changes). */
export function initSettings() {
  applySettings(current)
  window.matchMedia?.('(prefers-contrast: more)').addEventListener?.('change', () => {
    applySettings(current)
  })
}
