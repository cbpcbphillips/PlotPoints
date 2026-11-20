import { describe, expect, it } from 'vitest'
import { filmPath, parseFilmId, runtimeLabel } from './format'

describe('film page helpers', () => {
  it('parses only positive whole-number ids', () => {
    expect(parseFilmId('603')).toBe(603)
    for (const bad of [undefined, '', '0', '-5', '1.5', 'abc', '12abc', '99999999999999999999']) {
      expect(parseFilmId(bad)).toBeNull()
    }
  })

  it('formats runtimes', () => {
    expect(runtimeLabel(null)).toBe('')
    expect(runtimeLabel(45)).toBe('45m')
    expect(runtimeLabel(120)).toBe('2h')
    expect(runtimeLabel(136)).toBe('2h 16m')
  })

  it('builds the film path', () => {
    expect(filmPath(603)).toBe('/film/603')
  })
})
