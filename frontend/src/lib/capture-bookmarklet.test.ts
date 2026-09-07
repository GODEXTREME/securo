import { describe, expect, it } from 'vitest'
import { buildBookmarklet } from './capture-bookmarklet'

describe('buildBookmarklet', () => {
  const code = buildBookmarklet('https://securo.example.com/', 'sekrit')

  it('is one javascript: URI with no line breaks', () => {
    expect(code.startsWith('javascript:')).toBe(true)
    expect(code).not.toContain('\n')
  })

  it('points at the capture endpoint, without doubling the slash', () => {
    expect(code).toContain("'https://securo.example.com/api/receipt-capture'")
  })

  it('carries the secret and sends the page as text/plain', () => {
    expect(code).toContain("'sekrit'")
    expect(code).toContain("'Content-Type':'text/plain'")
    expect(code).toContain('documentElement.outerHTML')
  })

  it('uses no double quotes, so it survives a bookmark field', () => {
    expect(code).not.toContain('"')
  })
})
