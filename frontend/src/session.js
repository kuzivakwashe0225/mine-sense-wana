// Idle-session policy for signed-in users.
//
// What counts as activity (proof the person is still working):
//   * clicks, taps, key presses, typing in a form, scrolling or using the mouse wheel inside the app
//   * a successful change sent to the server (saving a record, reviewing one)
//   * sustained focus on something being read: the tab is visible, the window has focus and a reading surface
//     (a target card, the validation page, data sources, a record list) is on screen. Reading keeps the session
//     alive, but only for `readingMs` after the last real interaction, so a screen left on is still signed out.
// What does NOT count: moving the mouse, hovering, background polling, the page being open.
//
// Timeline: idle for (idleMs - warnMs) -> warning with a countdown -> idle for idleMs -> signed out, with the
// place the person was saved so signing back in returns them there.
// Keycloak's own SSO idle timeout is the server-side backstop if this code never runs (tab closed, tampered).

export const ACTIVITY_EVENTS = ['pointerdown', 'keydown', 'wheel', 'touchstart', 'input', 'change', 'scroll']
export const NOT_ACTIVITY = ['mousemove', 'pointermove', 'mouseover', 'pointerover', 'mouseenter', 'focus']

export class SessionPolicy {
  constructor({ idleMs, warnMs, readingMs, now = Date.now() }) {
    Object.assign(this, { idleMs, warnMs, readingMs })
    this.lastInteraction = now // real input
    this.lastActive = now // real input or credited reading
  }

  interact(t) {
    this.lastInteraction = Math.max(this.lastInteraction, t)
    this.lastActive = Math.max(this.lastActive, t)
  }

  /** Called on each tick while the person is reading. Credit stops `readingMs` after the last interaction. */
  reading(t) {
    const until = this.lastInteraction + this.readingMs
    this.lastActive = Math.max(this.lastActive, Math.min(t, until))
  }

  /** Merge activity seen in another tab of the same browser. */
  merge({ lastInteraction, lastActive }) {
    this.lastInteraction = Math.max(this.lastInteraction, lastInteraction || 0)
    this.lastActive = Math.max(this.lastActive, lastActive || 0)
  }

  expiresAt() { return this.lastActive + this.idleMs }

  phase(t) {
    const left = this.expiresAt() - t
    if (left <= 0) return { phase: 'expired', left: 0 }
    if (left <= this.warnMs) return { phase: 'warning', left }
    return { phase: 'active', left }
  }
}

const KEY = 'wana.session'

function load() { try { return JSON.parse(localStorage.getItem(KEY) || 'null') } catch { return null } }
function save(p) { try { localStorage.setItem(KEY, JSON.stringify({ lastInteraction: p.lastInteraction, lastActive: p.lastActive })) } catch { /* blocked */ } }
export function clearSessionClock() { try { localStorage.removeItem(KEY) } catch { /* blocked */ } }

function readingOnScreen() {
  if (document.visibilityState !== 'visible' || !document.hasFocus()) return false
  const h = window.innerHeight
  return [...document.querySelectorAll('[data-reading]')].some((el) => {
    const r = el.getBoundingClientRect()
    return r.bottom > 0 && r.top < h && r.height > 40
  })
}

/**
 * Watches the page and calls onPhase({phase, left}) when it changes and every second during the warning.
 * Activity in other tabs counts too (shared through localStorage), and survives a page refresh, so reloading
 * the page does not reset the clock. Returns { stop, stayActive, pause }.
 */
export function watchSession({ idleMs, warnMs, readingMs, onPhase, tickMs = 1000 }) {
  const policy = new SessionPolicy({ idleMs, warnMs, readingMs })
  const prev = load()
  if (prev) { policy.lastInteraction = prev.lastInteraction; policy.lastActive = prev.lastActive }
  else save(policy)
  let warned = false, lastSave = 0, last = ''

  const record = (t = Date.now()) => {
    if (warned) return // during the warning only the "Stay signed in" button counts
    policy.interact(t)
    if (t - lastSave > 2000) { save(policy); lastSave = t }
  }
  const onEvent = () => record()
  ACTIVITY_EVENTS.forEach((ev) => window.addEventListener(ev, onEvent, { passive: true, capture: true }))
  const onStorage = (e) => { if (e.key === KEY && e.newValue) { try { policy.merge(JSON.parse(e.newValue)) } catch { /* bad value */ } } }
  window.addEventListener('storage', onStorage)
  const onMutation = () => record()
  window.addEventListener('wana:activity', onMutation)

  const tick = () => {
    const t = Date.now()
    if (!warned && readingOnScreen()) { policy.reading(t); if (t - lastSave > 5000) { save(policy); lastSave = t } }
    const p = policy.phase(t)
    warned = p.phase === 'warning'
    const sig = p.phase === 'warning' ? `w${Math.ceil(p.left / 1000)}` : p.phase
    if (sig !== last) { last = sig; onPhase(p) }
    if (p.phase === 'expired') stop()
  }
  const timer = setInterval(tick, tickMs)
  tick()

  function stop() {
    clearInterval(timer)
    ACTIVITY_EVENTS.forEach((ev) => window.removeEventListener(ev, onEvent, { capture: true }))
    window.removeEventListener('storage', onStorage)
    window.removeEventListener('wana:activity', onMutation)
  }
  return {
    stop,
    stayActive() { warned = false; policy.interact(Date.now()); save(policy); tick() },
    policy,
  }
}

/** Mark a successful change sent to the server as activity (it proves the person is working). */
export function markActivity() { window.dispatchEvent(new Event('wana:activity')) }
