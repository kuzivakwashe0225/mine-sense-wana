// Thin API client. The geologist key lives only on this device (localStorage) and is sent as a Bearer token.
// The web app talks to its own origin. The Android app (mobile/) is built with VITE_API_BASE set to the server.
export const BASE = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '')
export const url = (path) => (path.startsWith('/') ? BASE + path : path)

const KEY = 'wana.geoKey'

export function getKey() {
  try { return localStorage.getItem(KEY) || '' } catch { return '' }
}
export function setKey(k) {
  try { k ? localStorage.setItem(KEY, k) : localStorage.removeItem(KEY) } catch { /* storage blocked */ }
}

function headers(extra = {}) {
  const k = getKey()
  return k ? { ...extra, Authorization: `Bearer ${k}` } : extra
}

async function handle(res) {
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`
    try { const j = await res.json(); if (j.detail) msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail) } catch { /* not json */ }
    const err = new Error(msg)
    err.status = res.status
    throw err
  }
  return res.json()
}

// Last good GET answers, so the map, targets and cards still open with no network. The web app also has
// the service worker cache; the Android app has only this. Keyed by role so a miner never sees geologist data.
const CACHE = 'wana.cache:'
function cacheKey(full) { return CACHE + (getKey() ? 'geo:' : 'miner:') + full }
function remember(full, data) {
  try { localStorage.setItem(cacheKey(full), JSON.stringify(data)) } catch { /* storage full or blocked */ }
  return data
}
function recall(full) {
  try { const s = localStorage.getItem(cacheKey(full)); return s ? JSON.parse(s) : undefined } catch { return undefined }
}

export const api = {
  get: (path, params) => {
    const q = params ? '?' + new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null)) : ''
    const full = url(path + q)
    return fetch(full, { headers: headers() }).then(handle).then((d) => remember(full, d), (e) => {
      // only fall back when the network failed, not when the server said no
      const hit = e.status ? undefined : recall(full)
      if (hit === undefined) throw e
      return hit
    })
  },
  post: (path, body) => fetch(url(path), {
    method: 'POST', headers: headers({ 'Content-Type': 'application/json' }), body: JSON.stringify(body ?? {}),
  }).then(handle),
  postForm: (path, form) => fetch(url(path), { method: 'POST', headers: headers(), body: form }).then(handle),
  // images behind the key: fetch as blob and hand back an object URL
  blobUrl: async (path) => {
    const r = await fetch(url(path), { headers: headers() })
    if (!r.ok) throw new Error(r.statusText)
    return URL.createObjectURL(await r.blob())
  },
}
