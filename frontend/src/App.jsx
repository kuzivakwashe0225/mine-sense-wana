import { useCallback, useEffect, useState } from 'react'
import { api, getKey, setKey } from './api'
import FieldApp from './FieldApp'
import MapView from './MapView'
import Review from './Review'
import Sources from './Sources'
import Validation from './Validation'

const TABS = [['map', 'Wana Map'], ['field', 'Wana Field'], ['review', 'Geologist review'], ['val', 'Validation'], ['data', 'Data sources']]

export default function App() {
  const [meta, setMeta] = useState(null)
  const [err, setErr] = useState('')
  const [tab, setTab] = useState(() => (location.hash.slice(1) || 'map'))
  const [lang, setLang] = useState(() => { try { return localStorage.getItem('wana.lang') || 'en' } catch { return 'en' } })
  const [planTarget, setPlanTarget] = useState('')
  const [keyOpen, setKeyOpen] = useState(false)
  const [keyDraft, setKeyDraft] = useState('')

  const loadMeta = useCallback(() => api.get('/api/meta').then((m) => { setMeta(m); setErr('') }).catch((e) => setErr(e.message)), [])
  useEffect(() => { loadMeta() }, [loadMeta])
  useEffect(() => { try { localStorage.setItem('wana.lang', lang) } catch { /* ignore */ } }, [lang])
  useEffect(() => { history.replaceState(null, '', `#${tab}`) }, [tab])

  if (err && !meta) return <div className="wrap"><h1 className="brand">MineSense <span>Wana</span></h1><div className="flag">Cannot reach the Wana server: {err}</div></div>
  if (!meta) return <div className="wrap muted">Loading…</div>
  const geo = meta.role === 'geologist'
  const tabs = TABS.filter(([k]) => k !== 'review' || geo)

  return (
    <div className="wrap">
      <header className="top">
        <div className="brand">
          <h1>MineSense <span>Wana</span></h1>
          <p>Chrome prospectivity · {meta.name} · model v{meta.version}</p>
        </div>
        <div className="top-ctl">
          <div className="seg" role="group" aria-label="Language">
            <button aria-pressed={lang === 'en'} onClick={() => setLang('en')}>English</button>
            <button aria-pressed={lang === 'sn'} onClick={() => setLang('sn')}>ChiShona</button>
          </div>
          <button className="btn sm" onClick={() => { setKeyDraft(''); setKeyOpen((o) => !o) }}>{geo ? 'Geologist ✓' : 'Miner view · sign in'}</button>
        </div>
      </header>
      {keyOpen && (
        <form className="panel keybox" onSubmit={(e) => { e.preventDefault(); setKey(keyDraft.trim()); setKeyOpen(false); loadMeta() }}>
          <label htmlFor="gkey">Geologist key</label>
          <input id="gkey" type="password" value={keyDraft} onChange={(e) => setKeyDraft(e.target.value)} placeholder={getKey() ? 'key saved on this device' : 'paste key'} />
          <button className="btn primary sm" type="submit">Save</button>
          {getKey() && <button className="btn sm" type="button" onClick={() => { setKey(''); setKeyOpen(false); loadMeta() }}>Sign out</button>}
        </form>
      )}
      {meta.sample_data && (
        <div className="demo-band"><b>Sample data.</b> One or more layers are synthetic (see Data sources). Results are for testing the system, not for decisions on real ground.</div>
      )}
      <nav className="tabs" role="tablist">
        {tabs.map(([k, label]) => <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}>{label}</button>)}
      </nav>
      <main className="view">
        {tab === 'map' && <MapView meta={meta} lang={lang} onPlan={(id) => { setPlanTarget(id); setTab('field') }} />}
        {tab === 'field' && <FieldApp lang={lang} initialTarget={planTarget} />}
        {tab === 'review' && geo && <Review onRetrained={loadMeta} />}
        {tab === 'val' && <Validation version={meta.version} />}
        {tab === 'data' && <Sources meta={meta} />}
      </main>
    </div>
  )
}
