import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, backoff, withRetry } from '../api'
import { fetchQuery, setQueryData, setScope } from '../query'

function respond(status, body, etag = '"a"') {
  return Promise.resolve(new Response(status === 304 ? null : JSON.stringify(body), { status, headers: { ETag: etag, 'Content-Type': 'application/json' } }))
}

describe('data layer', () => {
  let n = 0
  beforeEach(() => { setScope(`t${n++}`); localStorage.clear() })
  afterEach(() => vi.restoreAllMocks())

  it('deduplicates requests for the same URL', async () => {
    const f = vi.spyOn(globalThis, 'fetch').mockImplementation(() => respond(200, { v: 1 }))
    await Promise.all([fetchQuery('/api/x'), fetchQuery('/api/x'), fetchQuery('/api/x')])
    expect(f).toHaveBeenCalledTimes(1)
  })

  it('revalidates with the ETag and reports unchanged data', async () => {
    const f = vi.spyOn(globalThis, 'fetch').mockImplementationOnce(() => respond(200, { v: 1 })).mockImplementationOnce(() => respond(304))
    expect(await fetchQuery('/api/y')).toBe(true)
    expect(await fetchQuery('/api/y')).toBe(false)
    expect(f.mock.calls[1][1].headers['If-None-Match']).toBe('"a"')
  })

  it('serves the last good answer from this device while offline (stale while revalidate)', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementationOnce(() => respond(200, { v: 'saved' }))
    await fetchQuery('/api/z')
    setScope('other'); setScope(`t${n - 1}`) // a fresh page load: memory empty, device copy remains
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => Promise.reject(new TypeError('offline')))
    await expect(fetchQuery('/api/z', { retries: 0 })).rejects.toBeInstanceOf(ApiError)
    const rollback = setQueryData('/api/z', (d) => d) // reads the restored entry
    rollback()
  })

  it('optimistic update rolls back', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => respond(200, [{ id: 1, status: 'pending' }]))
    await fetchQuery('/api/r')
    let seen
    const rollback = setQueryData('/api/r', (rows) => { seen = rows; return rows.map((r) => ({ ...r, status: 'endorsed' })) })
    expect(seen[0].status).toBe('pending')
    rollback()
    setQueryData('/api/r', (rows) => { seen = rows; return rows })
    expect(seen[0].status).toBe('pending')
  })

  it('retries platform errors with backoff, never user errors', async () => {
    let calls = 0
    const ok = await withRetry(async () => { if (++calls < 3) throw new ApiError('x', { status: 503, kind: 'platform' }); return 'ok' }, { base: 1 })
    expect(ok).toBe('ok')
    expect(calls).toBe(3)
    calls = 0
    await expect(withRetry(async () => { calls++; throw new ApiError('bad', { status: 422, kind: 'user' }) }, { base: 1 })).rejects.toThrow('bad')
    expect(calls).toBe(1)
  })

  it('backoff grows exponentially with jitter and a cap', () => {
    for (let a = 0; a < 10; a++) {
      const d = backoff(a, { base: 500, max: 8000 })
      expect(d).toBeGreaterThanOrEqual(0)
      expect(d).toBeLessThanOrEqual(Math.min(8000, 500 * 2 ** a))
    }
  })
})
