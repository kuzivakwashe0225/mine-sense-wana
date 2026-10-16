// Offline outbox for field records (IndexedDB via Dexie). Records are saved on the phone first,
// then sent when there is network. client_id makes re-sending safe: the server ignores duplicates.
import Dexie from 'dexie'
import { api } from './api'

export const db = new Dexie('wana-field')
db.version(1).stores({ outbox: 'client_id, state, created_at' })

const listeners = new Set()
export function onOutboxChange(fn) { listeners.add(fn); return () => listeners.delete(fn) }
const notify = () => listeners.forEach((fn) => fn())

export async function queueRecord(rec, photoBlob) {
  await db.outbox.put({ ...rec, photo: photoBlob || null, state: 'queued', error: null })
  notify()
}

export async function listOutbox() {
  return db.outbox.orderBy('created_at').reverse().toArray()
}

let syncing = false
export async function syncOutbox() {
  if (syncing || !navigator.onLine) return { sent: 0, failed: 0, skipped: true }
  syncing = true
  let sent = 0, failed = 0
  try {
    const pending = await db.outbox.where('state').anyOf('queued', 'error').toArray()
    for (const r of pending) {
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
        // 4xx means the record itself is bad: keep it visible with the reason instead of retrying forever
        await db.outbox.update(r.client_id, { state: e.status && e.status < 500 ? 'rejected' : 'error', error: e.message })
        failed++
      }
    }
  } finally {
    syncing = false
    notify()
  }
  return { sent, failed }
}

if (typeof window !== 'undefined') {
  window.addEventListener('online', () => { syncOutbox() })
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
