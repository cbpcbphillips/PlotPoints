import { beforeEach, describe, expect, it } from 'vitest'
import { DEFAULTS, applySettings, readSettings, sanitize } from './settings'

beforeEach(() => {
  localStorage.clear()
  const root = document.documentElement
  for (const a of ['data-theme', 'data-contrast', 'data-reading', 'data-motion']) {
    root.removeAttribute(a)
  }
  root.style.fontSize = ''
})

describe('sanitize', () => {
  it('falls back to defaults for junk', () => {
    expect(sanitize(null)).toEqual(DEFAULTS)
    expect(sanitize('x')).toEqual(DEFAULTS)
    expect(
      sanitize({ theme: 'purple', contrast: 9, textScale: 73, dyslexia: 'yes', motion: 1 }),
    ).toEqual(DEFAULTS)
  })

  it('keeps valid values', () => {
    const s = { theme: 'dark', contrast: 'high', textScale: 125, dyslexia: true, motion: 'reduce' }
    expect(sanitize(s)).toEqual(s)
  })
})

describe('readSettings', () => {
  it('reads stored settings', () => {
    localStorage.setItem('pp-settings', JSON.stringify({ theme: 'light', textScale: 150 }))
    expect(readSettings()).toEqual({ ...DEFAULTS, theme: 'light', textScale: 150 })
  })

  it('migrates the old pp-theme toggle', () => {
    localStorage.setItem('pp-theme', 'dark')
    expect(readSettings().theme).toBe('dark')
  })

  it('prefers pp-settings over the old key', () => {
    localStorage.setItem('pp-theme', 'dark')
    localStorage.setItem('pp-settings', JSON.stringify({ theme: 'light' }))
    expect(readSettings().theme).toBe('light')
  })

  it('survives bad JSON', () => {
    localStorage.setItem('pp-settings', '{nope')
    expect(readSettings()).toEqual(DEFAULTS)
  })
})

describe('applySettings', () => {
  it('writes each choice as an attribute on <html>', () => {
    const root = document.documentElement
    applySettings(
      { theme: 'dark', contrast: 'high', textScale: 125, dyslexia: true, motion: 'reduce' },
      root,
    )
    expect(root.getAttribute('data-theme')).toBe('dark')
    expect(root.getAttribute('data-contrast')).toBe('more')
    expect(root.getAttribute('data-reading')).toBe('dyslexia')
    expect(root.getAttribute('data-motion')).toBe('reduce')
    expect(root.style.fontSize).toBe('125%')
  })

  it('clears everything when set back to the defaults', () => {
    const root = document.documentElement
    applySettings({ ...DEFAULTS, theme: 'dark', dyslexia: true, textScale: 150 }, root)
    applySettings({ ...DEFAULTS, contrast: 'standard' }, root)
    expect(root.hasAttribute('data-theme')).toBe(false)
    expect(root.hasAttribute('data-reading')).toBe(false)
    expect(root.hasAttribute('data-contrast')).toBe(false)
    expect(root.style.fontSize).toBe('')
  })
})
