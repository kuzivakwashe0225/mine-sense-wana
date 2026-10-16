// Where the person is in the app: tab, selected target, map view, layer switches, scroll position.
// Kept in sessionStorage so a browser refresh lands in the same place, and copied to a resume snapshot when a
// session expires so signing back in returns there too.
import { useCallback, useSyncExternalStore } from 'react'

const KEY = 'wana.ui'
const RESUME = 'wana.resume'
const RESUME_MAX_AGE = 12 * 3600 * 1000

let state = read()
const subs = new Set()

function read() { try { return JSON.parse(sessionStorage.getItem(KEY) || '{}') } catch { return {} } }
function write() { try { sessionStorage.setItem(KEY, JSON.stringify(state)) } catch { /* blocked */ } }

export function getUi(k, dflt) { return k in state ? state[k] : dflt }
export function setUi(k, v) {
  const next = typeof v === 'function' ? v(getUi(k)) : v
  if (state[k] === next) return
  state = { ...state, [k]: next }
  write()
  subs.forEach((fn) => fn())
}

export function useUi(k, dflt) {
  const sub = useCallback((fn) => { subs.add(fn); return () => subs.delete(fn) }, [])
  const v = useSyncExternalStore(sub, () => (k in state ? state[k] : dflt))
  return [v, useCallback((x) => setUi(k, x), [k])]
}

/** Save where this user is, before the session is ended for idleness. */
export function saveResume(sub) {
  try { localStorage.setItem(RESUME, JSON.stringify({ sub, at: Date.now(), ui: { ...state, scrollY: window.scrollY } })) } catch { /* blocked */ }
}

/** After sign-in: restore the snapshot only for the same person, and only if it is recent. */
export function takeResume(sub) {
  let r = null
  try { r = JSON.parse(localStorage.getItem(RESUME) || 'null') } catch { /* bad value */ }
  if (!r) return false
  if (r.sub !== sub || Date.now() - r.at > RESUME_MAX_AGE) {
    // someone else signed in on this device, or it is too old: never show them the previous user's place
    try { localStorage.removeItem(RESUME) } catch { /* blocked */ }
    return false
  }
  try { localStorage.removeItem(RESUME) } catch { /* blocked */ }
  state = { ...r.ui }
  write()
  subs.forEach((fn) => fn())
  if (r.ui.scrollY) setTimeout(() => window.scrollTo(0, r.ui.scrollY), 300)
  return true
}

export function hasResume() { try { return !!localStorage.getItem(RESUME) } catch { return false } }
export function dropResume() { try { localStorage.removeItem(RESUME) } catch { /* blocked */ } }
