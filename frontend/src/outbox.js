// Offline outbox for field records (IndexedDB via Dexie). Records are saved on the phone first,
// then sent when there is network and the person is signed in. client_id makes re-sending safe: the server
// ignores duplicates. Failed sends retry with jittered exponential backoff (2 s, 4 s, ... up to 5 min).
import Dexie from 'dexie'
import { api, backoff } from './api'
import { currentUser, signInRequired } from './auth'
import { markActivity } from './session'

export const db = new Dexie('wana-field')
db.version(1).stores({ outbox: 'client_id, state, created_at' })
// v2: the form being filled in is kept too, so a refresh, a crash or a sign-in never loses it
db.version(2).stores({ outbox: 'client_id, state, created_at', drafts: 'id' })

const listeners = new Set()
export function onOutboxChange(fn) { listeners.add(fn); return () => listeners.delete(fn) }
const notify = () => listeners.forEach((fn) => fn())

export async function queueRecord(rec, photoBlob) {
  await db.outbox.put({ ...rec, photo: photoBlob || null, state: 'queued', error: null, attempts: 0 })
  notify()
}

export async function listOutbox() {
  return db.outbox.orderBy('created_at').reverse().toArray()
}

export const saveDraft = (d) => db.drafts.put({ id: 'current', ...d, saved_at: Date.now() }).catch(() => {})
export const loadDraft = () => db.drafts.get('current').catch(() => null)
export const clearDraft = () => db.drafts.delete('current').catch(() => {})

let syncing = false
let retryTimer = null
let attempt = 0

function scheduleRetry() {
  clearTimeout(retryTimer)
  const ms = Math.max(2000, backoff(attempt++, { base: 2000, max: 300000 }))
  retryTimer = setTimeout(() => { syncOutbox() }, ms)
}

export async function syncOutbox() {
  if (syncing || !navigator.onLine) return { sent: 0, failed: 0, skipped: true }
  syncing = true
  let sent = 0, failed = 0, waitingAuth = 0
  try {
    const pending = await db.outbox.where('state').anyOf('queued', 'error', 'auth').toArray()
    for (const r of pending) {
      if (signInRequired() && !currentUser().signedIn) {
        await db.outbox.update(r.client_id, { state: 'auth', error: null })
        waitingAuth++
        continue
      }
      const f = new FormData()
      for (const k of ['client_id', 'sample_no', 'lon', 'lat', 'accuracy_m', 'notes', 'target_id', 'observer', 'created_at']) {
        if (r[k] !== undefined && r[k] !== null) f.append(k, String(r[k]))
      }
      f.append('checks', JSON.stringify(r.checks))
      if (r.photo) f.append('photo', r.photo, r.photo.name || 'photo.jpg')
      try {
        const res = await api.postForm('/api/records', f)
        await db.outbox.update(r.client_id, { state: 'sent', server_id: res.id, error: null, photo: null })
        sent++
      } catch (e) {
        // 401: keep it until the person signs in again. Other 4xx: the record itself is wrong, show why.
        // Network, 5xx, 429: try again later with backoff.
        const state = e.status === 401 ? 'auth' : e.retryable ? 'error' : 'rejected'
        await db.outbox.update(r.client_id, { state, error: state === 'auth' ? null : e.message, attempts: (r.attempts || 0) + 1 })
        if (state === 'error') failed++
        if (state === 'auth') waitingAuth++
      }
    }
  } finally {
    syncing = false
    notify()
  }
  if (sent) { attempt = 0; markActivity() }
  if (failed) scheduleRetry()
  return { sent, failed, waitingAuth }
}

if (typeof window !== 'undefined') {
  window.addEventListener('online', () => { attempt = 0; syncOutbox() })
}

// Per-device sample numbers so two phones never issue the same bag number.
export function nextSampleNo() {
  let dev = '', n = 0
  try {
    dev = localStorage.getItem('wana.device') || ''
    if (!dev) { dev = Math.random().toString(36).slice(2, 6).toUpperCase(); localStorage.setItem('wana.device', dev) }
    n = parseInt(localStorage.getItem('wana.seq') || '0', 10)
  } catch { dev = 'XXXX' }
  return { label: `WANA-SHU-${dev}-${String(n + 1).padStart(4, '0')}`, commit: () => { try { localStorage.setItem('wana.seq', String(n + 1)) } catch { /* ignore */ } } }
}
