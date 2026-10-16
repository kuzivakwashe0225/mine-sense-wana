import { useEffect, useState } from 'react'
import { signIn } from './auth'
import { CHECK_KEYS, T } from './i18n'
import { clearDraft, listOutbox, loadDraft, nextSampleNo, onOutboxChange, queueRecord, saveDraft, syncOutbox } from './outbox'
import { useQuery } from './query'

const ICONS = {
  black_grains: <svg viewBox="0 0 48 48" aria-hidden="true"><path d="M8 32l8-14 9 4 6-10 9 18-6 8H14z" fill="#3a3f42" /><circle cx="18" cy="26" r="2.4" fill="#111" /><circle cx="27" cy="29" r="2.8" fill="#111" /><circle cx="33" cy="25" r="2" fill="#111" /><path d="M17 24.5l1.5-1M26 27.5l1.5-1" stroke="#fff" strokeWidth="1.2" /></svg>,
  heavy: <svg viewBox="0 0 48 48" aria-hidden="true"><path d="M10 40h28" stroke="#5A6661" strokeWidth="2" /><path d="M14 30c0-6 4-10 10-10s10 4 10 10v4H14z" fill="#3a3f42" /><path d="M24 6v10M19 11l5 5 5-5" stroke="#B4532A" strokeWidth="3" fill="none" /></svg>,
  brown_streak: <svg viewBox="0 0 48 48" aria-hidden="true"><rect x="6" y="20" width="36" height="20" rx="2" fill="#F1ECE3" stroke="#B9AFA0" /><path d="M12 32c8-4 16-4 26-6" stroke="#7A4A26" strokeWidth="4" strokeLinecap="round" /><path d="M30 6l10 12-6 4-10-12z" fill="#3a3f42" /></svg>,
  green_host: <svg viewBox="0 0 48 48" aria-hidden="true"><path d="M6 34l10-16 10 6 8-12 8 22z" fill="#5E8C6E" /><path d="M14 30c4-2 8 0 12-2s8 0 10-2" stroke="#9CC2A8" strokeWidth="2" fill="none" /></svg>,
  old_pits: <svg viewBox="0 0 48 48" aria-hidden="true"><path d="M4 22h40" stroke="#7A4A26" strokeWidth="3" /><path d="M16 22l3 20h10l3-20" fill="#2a2a2a" /><path d="M24 4l10 16H14z" fill="#E0B055" stroke="#9A6A12" /><rect x="23" y="9" width="2" height="6" fill="#111" /><rect x="23" y="16.5" width="2" height="2" fill="#111" /></svg>,
}

async function shrink(file, max = 1600) {
  try {
    const bmp = await createImageBitmap(file)
    const s = Math.min(1, max / Math.max(bmp.width, bmp.height))
    const c = document.createElement('canvas')
    c.width = Math.round(bmp.width * s); c.height = Math.round(bmp.height * s)
    c.getContext('2d').drawImage(bmp, 0, 0, c.width, c.height)
    const blob = await new Promise((r) => c.toBlob(r, 'image/jpeg', 0.82))
    return new File([blob], 'photo.jpg', { type: 'image/jpeg' })
  } catch { return file }
}

// crypto.randomUUID only exists on HTTPS pages; getRandomValues works everywhere
function uuid4() {
  if (crypto.randomUUID) return crypto.randomUUID()
  const b = crypto.getRandomValues(new Uint8Array(16))
  b[6] = (b[6] & 0x0f) | 0x40; b[8] = (b[8] & 0x3f) | 0x80
  const h = [...b].map((x) => x.toString(16).padStart(2, '0')).join('')
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`
}

const empty = () => ({ checks: Object.fromEntries(CHECK_KEYS.map((k) => [k, false])), notes: '', pos: null, photo: null, preview: null })

const NONE = []

export default function FieldApp({ lang, initialTarget, user, authEnabled }) {
  const t = T[lang]
  const targets = useQuery('/api/targets').data || NONE
  const [target, setTarget] = useState(initialTarget || '')
  const [f, setF] = useState(empty)
  const [online, setOnline] = useState(navigator.onLine)
  const [msg, setMsg] = useState(null)
  const [locating, setLocating] = useState(false)
  const [manual, setManual] = useState({ lat: '', lon: '' })
  const [outbox, setOutbox] = useState([])
  const [observer, setObserver] = useState(() => { try { return localStorage.getItem('wana.observer') || user?.name || '' } catch { return '' } })
  const [sample, setSample] = useState(nextSampleNo)

  useEffect(() => { if (!target && targets[0]) setTarget(targets[0].id) }, [target, targets])
  // the form being filled in is saved on the phone as it changes, so nothing typed is lost to a refresh,
  // a sign-in, an expired session or a flat battery
  const [draftLoaded, setDraftLoaded] = useState(false)
  useEffect(() => {
    loadDraft().then((d) => {
      if (d) {
        setF((s) => ({ ...s, checks: d.checks || s.checks, notes: d.notes || '', pos: d.pos || null,
          photo: d.photo || null, preview: d.photo ? URL.createObjectURL(d.photo) : null }))
        if (d.manual) setManual(d.manual)
        if (d.target && !initialTarget) setTarget(d.target)
      }
      setDraftLoaded(true)
    })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (draftLoaded) saveDraft({ checks: f.checks, notes: f.notes, pos: f.pos, photo: f.photo, manual, target })
  }, [draftLoaded, f.checks, f.notes, f.pos, f.photo, manual, target])
  useEffect(() => { if (initialTarget) setTarget(initialTarget) }, [initialTarget])
  useEffect(() => {
    const refresh = () => listOutbox().then(setOutbox)
    refresh()
    const off = onOutboxChange(refresh)
    const up = () => setOnline(true), down = () => setOnline(false)
    window.addEventListener('online', up); window.addEventListener('offline', down)
    return () => { off(); window.removeEventListener('online', up); window.removeEventListener('offline', down) }
  }, [])

  const gps = () => {
    if (!('geolocation' in navigator)) { setMsg({ text: t.gpsErr, bad: true }); return }
    setLocating(true)
    navigator.geolocation.getCurrentPosition(
      (p) => { setLocating(false); setF((s) => ({ ...s, pos: { lat: p.coords.latitude, lon: p.coords.longitude, acc: Math.round(p.coords.accuracy) } })) },
      () => { setLocating(false); setMsg({ text: t.gpsErr, bad: true }) },
      { enableHighAccuracy: true, timeout: 30000, maximumAge: 0 },
    )
  }

  const save = async () => {
    let pos = f.pos
    if (!pos && manual.lat && manual.lon) {
      const lat = parseFloat(manual.lat), lon = parseFloat(manual.lon)
      if (Number.isFinite(lat) && Number.isFinite(lon)) pos = { lat: -Math.abs(lat), lon, acc: null }
    }
    if (!pos) { setMsg({ text: t.needLoc, bad: true }); return }
    const rec = {
      client_id: uuid4(), sample_no: sample.label, target_id: target === 'NEW' ? '' : target,
      lon: pos.lon, lat: pos.lat, accuracy_m: pos.acc, checks: f.checks, notes: f.notes, observer,
      created_at: new Date().toISOString(),
    }
    await queueRecord(rec, f.photo)
    await clearDraft()
    sample.commit()
    setSample(nextSampleNo())
    try { localStorage.setItem('wana.observer', observer) } catch { /* ignore */ }
    if (f.preview) URL.revokeObjectURL(f.preview)
    setF(empty()); setManual({ lat: '', lon: '' })
    if (navigator.onLine) {
      const r = await syncOutbox()
      setMsg(r.waitingAuth ? { text: t.needSignIn, bad: true } : r.failed ? { text: t.savedOffline, bad: true } : { text: t.sentOk })
    } else setMsg({ text: t.savedOffline, bad: true })
  }

  const waiting = outbox.filter((o) => o.state !== 'sent').length
  return (
    <div className="fieldgrid">
      <div className="phoneish">
        <div className="appbar"><b>{t.fieldTitle}</b><span className={`net ${online ? 'on' : 'off'}`}>{online ? t.online : t.offline}</span></div>
        <div className="appbody">
          <div className="toast warn small">{t.rules}</div>
          <div>
            <label className="fl" htmlFor="ftarget">{t.target}</label>
            <select id="ftarget" value={target} onChange={(e) => setTarget(e.target.value)}>
              {targets.map((x) => <option key={x.id} value={x.id}>{x.id} · {Math.round(x.score)}/100</option>)}
              <option value="NEW">{t.newLoc}</option>
            </select>
          </div>
          <div>
            <div className="fl">{t.gps}</div>
            <div className="gps">
              <span className="mono small">{f.pos ? <>{Math.abs(f.pos.lat).toFixed(5)}°S<br />{f.pos.lon.toFixed(5)}°E · ±{f.pos.acc} m</> : locating ? t.locating : '—'}</span>
              <button className="appbtn sec" onClick={gps} disabled={locating}>{t.capture}</button>
            </div>
            {!f.pos && (
              <div className="manual">
                <span className="small muted">{t.manual}</span>
                <input id="mlat" inputMode="decimal" placeholder="lat e.g. -19.664" value={manual.lat} onChange={(e) => setManual((m) => ({ ...m, lat: e.target.value }))} />
                <input id="mlon" inputMode="decimal" placeholder="lon e.g. 30.012" value={manual.lon} onChange={(e) => setManual((m) => ({ ...m, lon: e.target.value }))} />
              </div>
            )}
          </div>
          <div>
            <div className="fl">{t.seeQ}</div>
            <div className="tiles">
              {CHECK_KEYS.map((k) => (
                <button key={k} type="button" className={`tile ${k === 'old_pits' ? 'warnt' : ''}`} aria-pressed={f.checks[k]}
                  onClick={() => setF((s) => ({ ...s, checks: { ...s.checks, [k]: !s.checks[k] } }))}>
                  {ICONS[k]}<span>{t.q[k]}</span><span className="yn">{f.checks[k] ? t.yes : t.tapYes}</span>
                </button>
              ))}
            </div>
          </div>
          <div>
            <div className="fl">{t.photo}</div>
            <div className="photo">
              {f.preview && <img src={f.preview} alt="" />}
              <label className="appbtn sec">{t.addPhoto}
                <input type="file" accept="image/*" capture="environment" hidden onChange={async (e) => {
                  const file = e.target.files?.[0]; if (!file) return
                  const small = await shrink(file)
                  setF((s) => ({ ...s, photo: small, preview: URL.createObjectURL(small) }))
                }} />
              </label>
            </div>
          </div>
          <div><div className="fl">{t.sample}</div><div className="samp">{sample.label}</div><div className="small muted">Write this on the sample bag.</div></div>
          <div><label className="fl" htmlFor="fobs">{t.observer}</label><input id="fobs" value={observer} onChange={(e) => setObserver(e.target.value)} /></div>
          <div><label className="fl" htmlFor="fnotes">{t.notes}</label><textarea id="fnotes" rows={2} placeholder={t.notesPh} value={f.notes} onChange={(e) => setF((s) => ({ ...s, notes: e.target.value }))} /></div>
          {msg && <div className={`toast ${msg.bad ? 'warn' : ''}`}>{msg.text}</div>}
          <button className="appbtn" onClick={save}>{t.save}</button>
          {waiting > 0 && authEnabled && !user.signedIn && <button className="appbtn" onClick={signIn}>{t.signInToSend} ({waiting})</button>}
          {waiting > 0 && (user.signedIn || !authEnabled) && <button className="appbtn sec" disabled={!online} onClick={() => syncOutbox()}>{t.sync} ({waiting})</button>}
          {outbox.length > 0 && (
            <div>
              <div className="fl">{t.outbox}</div>
              <ul className="outbox">
                {outbox.slice(0, 8).map((o) => (
                  <li key={o.client_id}><span className="mono small">{o.sample_no}</span><span className={`st ${o.state}`}>{t.st[o.state]}</span>
                    {o.error && <span className="small muted"> {o.error}</span>}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
      <div className="explain">
        <h2>Checking a target in the field</h2>
        <p>This screen is the Wana Field app. On an Android phone, open the site in Chrome and choose <b>Add to Home screen</b>: it then opens like an app and works with no network.</p>
        <ol>
          <li><b>Location</b> comes from the phone's GPS, with its accuracy. If GPS fails, type the coordinates.</li>
          <li><b>Picture checklist</b>: five tap-to-answer pictures, one of them a safety check.</li>
          <li><b>Photo</b> is shrunk on the phone before sending, to save data.</li>
          <li><b>Sample bag numbers</b> include a code for this phone, so two phones never print the same number.</li>
          <li>Records are <b>saved on the phone first</b> and sent automatically when signal returns. Sending twice is safe.</li>
          <li>Sending needs a Wana account, so each record has a known author. Records made while signed out or offline wait on the phone until you sign in.</li>
          <li>Nothing changes the map until the geologist endorses it.</li>
        </ol>
      </div>
    </div>
  )
}
