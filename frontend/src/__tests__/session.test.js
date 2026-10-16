import { describe, expect, it } from 'vitest'
import { ACTIVITY_EVENTS, NOT_ACTIVITY, SessionPolicy } from '../session'

const MIN = 60000
const policy = () => new SessionPolicy({ idleMs: 15 * MIN, warnMs: MIN, readingMs: 30 * MIN, now: 0 })

describe('session policy', () => {
  it('mouse movement is not activity', () => {
    for (const ev of NOT_ACTIVITY) expect(ACTIVITY_EVENTS).not.toContain(ev)
    expect(ACTIVITY_EVENTS).toEqual(expect.arrayContaining(['pointerdown', 'keydown', 'input', 'scroll']))
  })

  it('warns 60 seconds before expiry, then expires', () => {
    const p = policy()
    expect(p.phase(13 * MIN).phase).toBe('active')
    const w = p.phase(14 * MIN + 1000)
    expect(w.phase).toBe('warning')
    expect(Math.ceil(w.left / 1000)).toBe(59)
    expect(p.phase(15 * MIN).phase).toBe('expired')
  })

  it('an interaction restarts the clock', () => {
    const p = policy()
    p.interact(10 * MIN)
    expect(p.phase(20 * MIN).phase).toBe('active')
    expect(p.expiresAt()).toBe(25 * MIN)
  })

  it('sustained reading keeps the session alive, but only up to the reading limit', () => {
    const p = policy()
    for (let t = 0; t <= 40 * MIN; t += 5000) {
      p.reading(t)
      if (t === 20 * MIN) expect(p.phase(t).phase).toBe('active') // reading 20 minutes: still signed in
    }
    // credit stopped at 30 min after the last interaction; 15 more idle minutes and it expires
    expect(p.expiresAt()).toBe(45 * MIN)
    expect(p.phase(44.5 * MIN).phase).toBe('warning')
    expect(p.phase(45 * MIN).phase).toBe('expired')
  })

  it('stopping reading starts the normal countdown from that moment', () => {
    const p = policy()
    for (let t = 0; t <= 10 * MIN; t += 5000) p.reading(t)
    expect(p.expiresAt()).toBe(25 * MIN)
  })

  it('activity in another tab counts here', () => {
    const p = policy()
    p.merge({ lastInteraction: 12 * MIN, lastActive: 12 * MIN })
    expect(p.phase(20 * MIN).phase).toBe('active')
    p.merge({ lastInteraction: 1, lastActive: 1 }) // older news never moves the clock back
    expect(p.expiresAt()).toBe(27 * MIN)
  })
})
