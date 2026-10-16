// API client: one place for tokens, error classification, retries and streaming.
// The web app talks to its own origin. The Android app (mobile/) is built with VITE_API_BASE set to the server.
export const BASE = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '')
export const url = (path) => (path.startsWith('/') ? BASE + path : path)

// ---------- errors ----------
// kind: 'user' (fix your input) | 'business' (a rule says no) | 'platform' (our fault) | 'network' (no connection)
export class ApiError extends Error {
  constructor(message, { status = 0, kind = 'platform', code = '', requestId = '', retryAfter = 0 } = {}) {
    super(message)
    Object.assign(this, { status, kind, code, requestId, retryAfter })
  }
  get retryable() { return this.kind === 'network' || this.status >= 500 || this.status === 429 || this.status === 408 }
}

const FRIENDLY = {
  network: 'No connection to the Wana server. Your work is kept on this device.',
  platform: 'Something went wrong on our side. It has been logged; please try again.',
}

async function toError(res) {
  let body = {}
  try { body = await res.json() } catch { /* not json */ }
  const e = body.error || {}
  const kind = e.kind || (res.status >= 500 ? 'platform' : res.status === 409 ? 'business' : 'user')
  const msg = typeof body.detail === 'string' ? body.detail : (FRIENDLY[kind] || `${res.status} ${res.statusText}`)
  return new ApiError(msg, { status: res.status, kind, code: e.code || '', requestId: e.request_id || res.headers.get('x-request-id') || '',
    retryAfter: Number(res.headers.get('retry-after')) || 0 })
}

// ---------- auth hooks (set by auth.js) ----------
let tokenFn = async () => ''
let onAuthLost = () => {}
export function setAuthHooks({ token, authLost }) { tokenFn = token; onAuthLost = authLost }

async function send(method, path, { body, form, headers = {}, signal, retryAuth = true } = {}) {
  const h = { ...headers }
  const tok = await tokenFn()
  if (tok) h.Authorization = `Bearer ${tok}`
  if (body !== undefined) h['Content-Type'] = 'application/json'
  let res
  try {
    res = await fetch(url(path), { method, headers: h, signal, body: form ?? (body !== undefined ? JSON.stringify(body) : undefined) })
  } catch (e) {
    if (e.name === 'AbortError') throw e
    throw new ApiError(FRIENDLY.network, { kind: 'network' })
  }
  if (res.status === 401 && tok && retryAuth) {
    // the token may have expired between our check and the server's: refresh once, then give up
    const fresh = await tokenFn({ force: true })
    if (fresh && fresh !== tok) return send(method, path, { body, form, headers, signal, retryAuth: false })
    onAuthLost()
  }
  if (!res.ok && res.status !== 304) {
    const err = await toError(res)
    if (err.kind === 'platform') reportError(err, `${method} ${path}`)
    throw err
  }
  return res
}

// ---------- retry with backoff ----------
const sleep = (ms, signal) => new Promise((resolve, reject) => {
  const t = setTimeout(resolve, ms)
  signal?.addEventListener('abort', () => { clearTimeout(t); reject(new DOMException('aborted', 'AbortError')) }, { once: true })
})

export function backoff(attempt, { base = 500, max = 15000 } = {}) {
  // "full jitter": spreads retries from many phones so they don't all hit the server at the same moment
  return Math.round(Math.random() * Math.min(max, base * 2 ** attempt))
}

export async function withRetry(fn, { retries = 3, signal, base, max } = {}) {
  for (let attempt = 0; ; attempt++) {
    try { return await fn() } catch (e) {
      if (!(e instanceof ApiError) || !e.retryable || attempt >= retries) throw e
      if (e.kind === 'network' && typeof navigator !== 'undefined' && !navigator.onLine) throw e // wait for 'online' instead
      await sleep(e.retryAfter ? e.retryAfter * 1000 : backoff(attempt, { base, max }), signal)
    }
  }
}

export const newKey = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`)

export const api = {
  // conditional GET for the query layer: returns {status, data, etag}
  async getRaw(path, { etag, signal } = {}) {
    const res = await send('GET', path, { headers: etag ? { 'If-None-Match': etag } : {}, signal })
    if (res.status === 304) return { status: 304, data: undefined, etag }
    return { status: res.status, data: await res.json(), etag: res.headers.get('etag') || '' }
  },
  get: (path, params) => {
    const q = params ? '?' + new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null)) : ''
    return withRetry(() => send('GET', path + q)).then((r) => r.json())
  },
  // mutations carry an Idempotency-Key, so a retry after a lost answer cannot apply the change twice
  post: (path, body, { idempotencyKey = newKey(), retries = 2 } = {}) =>
    withRetry(() => send('POST', path, { body: body ?? {}, headers: { 'Idempotency-Key': idempotencyKey } }), { retries }).then((r) => r.json()),
  postForm: (path, form) => send('POST', path, { form }).then((r) => r.json()),
  blobUrl: async (path) => URL.createObjectURL(await (await withRetry(() => send('GET', path))).blob()),
  // newline-delimited JSON stream: calls onEvent for each line as it arrives
  async stream(path, onEvent, { body, signal } = {}) {
    const res = await send('POST', path, { body: body ?? {}, signal })
    const reader = res.body.getReader()
    const dec = new TextDecoder()
    let buf = ''
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      buf += dec.decode(value, { stream: true })
      let i
      while ((i = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, i).trim()
        buf = buf.slice(i + 1)
        if (line) onEvent(JSON.parse(line))
      }
    }
    if (buf.trim()) onEvent(JSON.parse(buf))
  },
}

// ---------- client error reporting ----------
let sent = []
export function reportError(err, where = '') {
  const now = Date.now()
  sent = sent.filter((t) => now - t < 60000)
  if (sent.length >= 10 || (typeof navigator !== 'undefined' && !navigator.onLine)) return
  sent.push(now)
  const kind = err instanceof ApiError ? err.kind : 'platform'
  if (kind === 'user') return // the person can fix these; they are counted on the server already
  fetch(url('/api/client-errors'), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, keepalive: true,
    body: JSON.stringify({ kind, message: String(err?.message || err).slice(0, 500), code: err?.code || '',
      where: String(where).slice(0, 200), request_id: err?.requestId || '', stack: String(err?.stack || '').slice(0, 2000) }),
  }).catch(() => {})
}

api.put = (path, body) => withRetry(() => send('PUT', path, { body }), { retries: 1 }).then((r) => r.json())
