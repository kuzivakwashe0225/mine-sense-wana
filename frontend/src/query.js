// Small data layer for GET requests:
//  * request deduplication  - components asking for the same URL at once share one request
//  * stale-while-revalidate - show the last answer at once (memory, then this device), refresh in the background
//  * smart polling          - poll fast after changes, slow down while nothing changes, pause when hidden or offline
//  * retry with backoff     - transient failures retry with jittered exponential backoff
//  * optimistic updates     - setQueryData() changes the cache now and hands back a rollback
// ETags make most polls an empty 304.
import { useCallback, useEffect, useRef, useSyncExternalStore } from 'react'
import { api, withRetry } from './api'

const store = new Map()
let scope = 'anon' // whose cache: answers depend on the signed-in role, so each user gets their own
const PERSIST = 'wana.q:'

export function setScope(s) {
  if (s === scope) return
  scope = s
  store.clear()
}

export function keyOf(path, params) {
  if (!params) return path
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ''))
  return q.toString() ? `${path}?${q}` : path
}

function entry(key) {
  let e = store.get(key)
  if (!e) {
    e = { data: undefined, etag: '', at: 0, error: null, inflight: null, validating: false, subs: new Set(), snap: null }
    const saved = readPersisted(key)
    if (saved) Object.assign(e, { data: saved.data, etag: saved.etag, at: 0 }) // stale until revalidated
    store.set(key, e)
  }
  return e
}

function readPersisted(key) {
  try { const s = localStorage.getItem(`${PERSIST}${scope}:${key}`); return s ? JSON.parse(s) : null } catch { return null }
}
function persist(key, e) {
  try { localStorage.setItem(`${PERSIST}${scope}:${key}`, JSON.stringify({ data: e.data, etag: e.etag })) } catch { /* full or blocked */ }
}
export function clearPersisted(forScope) {
  try {
    Object.keys(localStorage).filter((k) => k.startsWith(`${PERSIST}${forScope}:`)).forEach((k) => localStorage.removeItem(k))
  } catch { /* blocked */ }
}

function notify(e) { e.snap = null; e.subs.forEach((fn) => fn()) }

/** Fetch (or join the request already in flight). Resolves to true when the data changed. */
export function fetchQuery(key, { retries = 3 } = {}) {
  const e = entry(key)
  if (e.inflight) return e.inflight
  e.validating = true
  notify(e)
  const run = withRetry(() => api.getRaw(key, { etag: e.data !== undefined ? e.etag : '' }), { retries })
    .then((r) => {
      let changed = false
      if (r.status !== 304) {
        changed = JSON.stringify(r.data) !== JSON.stringify(e.data)
        e.data = r.data
        e.etag = r.etag
        persist(key, e)
      }
      e.at = Date.now()
      e.error = null
      return changed
    }, (err) => {
      e.error = err
      throw err
    })
    .finally(() => { e.inflight = null; e.validating = false; notify(e) })
  e.inflight = run
  return run
}

/** Optimistic update. Returns a function that puts the previous value back. */
export function setQueryData(key, updater) {
  const e = entry(key)
  const prev = e.data
  e.data = typeof updater === 'function' ? updater(prev) : updater
  notify(e)
  return () => { e.data = prev; notify(e) }
}

export function invalidate(prefix) {
  for (const [k, e] of store) if (k.startsWith(prefix) && e.subs.size) fetchQuery(k).catch(() => {})
}

const visible = () => typeof document === 'undefined' || document.visibilityState === 'visible'
const online = () => typeof navigator === 'undefined' || navigator.onLine

/**
 * useQuery(path, params, { poll: { min, max }, enabled })
 * returns { data, error, loading, validating, stale, refresh }
 */
export function useQuery(path, params, { poll, enabled = true, staleMs = 5000 } = {}) {
  const key = enabled && path ? keyOf(path, params) : null
  const subscribe = useCallback((fn) => {
    if (!key) return () => {}
    const e = entry(key)
    e.subs.add(fn)
    return () => e.subs.delete(fn)
  }, [key])
  const snapshot = useCallback(() => {
    if (!key) return EMPTY
    const e = entry(key)
    if (!e.snap) e.snap = { data: e.data, error: e.error, validating: e.validating, at: e.at }
    return e.snap
  }, [key])
  const s = useSyncExternalStore(subscribe, snapshot)
  const delay = useRef(poll?.min)

  useEffect(() => {
    if (!key) return
    let timer, stopped = false
    const e = entry(key)
    const revalidate = () => {
      if (!online()) return Promise.resolve(false)
      return fetchQuery(key).then((changed) => {
        if (poll) delay.current = changed ? poll.min : Math.min(poll.max, Math.round(delay.current * 1.6))
        return changed
      }, () => { if (poll) delay.current = Math.min(poll.max, delay.current * 2) })
    }
    const schedule = () => {
      if (!poll || stopped) return
      clearTimeout(timer)
      timer = setTimeout(async () => {
        if (visible() && online()) await revalidate()
        schedule()
      }, delay.current)
    }
    if (e.data === undefined || Date.now() - e.at > staleMs) revalidate()
    delay.current = poll?.min
    schedule()
    // coming back to the tab, or back online: check now instead of waiting for the next tick
    const wake = () => {
      if (visible() && online() && Date.now() - entry(key).at > staleMs) {
        if (poll) delay.current = poll.min
        revalidate().finally(schedule)
      }
    }
    document.addEventListener('visibilitychange', wake)
    window.addEventListener('online', wake)
    window.addEventListener('focus', wake)
    return () => {
      stopped = true
      clearTimeout(timer)
      document.removeEventListener('visibilitychange', wake)
      window.removeEventListener('online', wake)
      window.removeEventListener('focus', wake)
    }
  }, [key, poll?.min, poll?.max, staleMs]) // eslint-disable-line react-hooks/exhaustive-deps

  const refresh = useCallback(() => (key ? fetchQuery(key) : Promise.resolve(false)), [key])
  return { data: s.data, error: s.error, loading: s.data === undefined && !s.error, validating: s.validating,
    stale: s.at === 0 && s.data !== undefined, refresh, key }
}

const EMPTY = { data: undefined, error: null, validating: false, at: 0 }
