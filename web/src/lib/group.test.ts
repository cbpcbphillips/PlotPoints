import { describe, expect, it } from 'vitest'
import { MAX_NAME, uniqueName } from './group'

describe('uniqueName', () => {
  it('keeps a free name as it is', () => {
    expect(uniqueName('Sam', ['Alex'])).toBe('Sam')
  })

  it('numbers a clash, ignoring case', () => {
    expect(uniqueName('sam', ['Sam'])).toBe('sam 2')
    expect(uniqueName('Sam', ['Sam', 'Sam 2'])).toBe('Sam 3')
  })

  it('falls back to Guest for an empty name', () => {
    expect(uniqueName('  ', [])).toBe('Guest')
    expect(uniqueName('', ['Guest'])).toBe('Guest 2')
  })

  it('never goes past the API name limit', () => {
    const long = 'x'.repeat(100)
    const first = uniqueName(long, [])
    expect(first.length).toBeLessThanOrEqual(MAX_NAME)
    expect(uniqueName(long, [first]).length).toBeLessThanOrEqual(MAX_NAME)
  })
})
