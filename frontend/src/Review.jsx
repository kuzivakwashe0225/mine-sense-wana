import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import { CHECK_KEYS } from './i18n'

export default function Review({ onRetrained }) {
  const [rows, setRows] = useState([])
  const [versions, setVersions] = useState([])
  const [lab, setLab] = useState({})
  const [diff, setDiff] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [photos, setPhotos] = useState({})

  const load = useCallback(() => {
    api.get('/api/records').then(setRows).catch((e) => setErr(e.message))
    api.get('/api/model/versions').then(setVersions)
  }, [])
  useEffect(load, [load])
  useEffect(() => {
    rows.filter((r) => r.photo && !photos[r.photo]).forEach((r) =>
      api.blobUrl(`/api/photos/${r.photo}`).then((u) => setPhotos((p) => ({ ...p, [r.photo]: u }))).catch(() => {}))
  }, [rows, photos])

  const decide = async (r, status) => {
    setErr('')
    const v = lab[r.id] ?? r.lab_cr2o3
    try {
      await api.post(`/api/records/${r.id}/review`, { status, lab_cr2o3: v === '' || v == null ? null : Number(v) })
      load()
    } catch (e) { setErr(e.message) }
  }
  const retrain = async () => {
    setBusy(true); setErr('')
    try { const d = await api.post('/api/model/retrain'); setDiff(d); load(); onRetrained() } catch (e) { setErr(e.message) }
    setBusy(false)
  }
  const ready = rows.filter((r) => r.status !== 'pending' && r.used_in_version == null).length
  return (
    <div>
      <div className="reviewbar">
        <div>
          <h2>Field records</h2>
          <p className="muted">Enter the ZIMLABS Cr₂O₃ result, endorse or reject, then update the map. Each update is a new, logged model version; reviewed records used in a version are locked.</p>
        </div>
        <button className="btn lat" disabled={!ready || busy} onClick={retrain}>{busy ? 'Training…' : `Update map with ${ready} reviewed record${ready === 1 ? '' : 's'}`}</button>
      </div>
      {err && <div className="flag">{err}</div>}
      <div className="tablewrap"><table>
        <thead><tr><th>Sample</th><th>Target</th><th>Location</th><th>Checklist</th><th>Photo / notes</th><th>Lab Cr₂O₃ %</th><th>Status</th><th>Decision</th></tr></thead>
        <tbody>
          {rows.length === 0 && <tr><td colSpan={8} className="muted">No field records yet. Send one from the Wana Field tab.</td></tr>}
          {rows.map((r) => {
            const locked = r.used_in_version != null
            const signs = CHECK_KEYS.slice(0, 4).filter((k) => r.checks[k]).length
            return (
              <tr key={r.id}>
                <td className="mono">{r.sample_no}<div className="small muted">{r.observer}</div></td>
                <td>{r.target_id || 'new location'}</td>
                <td className="mono small">{Math.abs(r.lat).toFixed(5)}°S<br />{r.lon.toFixed(5)}°E{r.accuracy_m ? ` ±${Math.round(r.accuracy_m)} m` : ' (typed)'}</td>
                <td><div className="cl">{CHECK_KEYS.map((k, j) => <i key={k} title={k} className={r.checks[k] ? (j === 4 ? 'h' : 'y') : ''} />)}</div>
                  <div className="small muted">{signs}/4 chromite signs{r.checks.old_pits ? ' · old pits' : ''}</div></td>
                <td className="notes">{r.photo && photos[r.photo] && <a href={photos[r.photo]} target="_blank" rel="noreferrer"><img src={photos[r.photo]} alt="" /></a>}<span className="small">{r.notes || <span className="muted">no notes</span>}</span></td>
                <td><input type="number" min="0" max="70" step="0.1" aria-label={`Lab result ${r.sample_no}`} disabled={locked}
                  value={lab[r.id] ?? r.lab_cr2o3 ?? ''} onChange={(e) => setLab((l) => ({ ...l, [r.id]: e.target.value }))} /></td>
                <td><span className={`st ${locked ? 'used' : r.status}`}>{locked ? `in model v${r.used_in_version}` : r.status}</span></td>
                <td>{!locked && <div className="row"><button className="btn sm" onClick={() => decide(r, 'endorsed')}>Chrome</button><button className="btn sm" onClick={() => decide(r, 'rejected')}>Not chrome</button></div>}</td>
              </tr>
            )
          })}
        </tbody>
      </table></div>
      <div className="changes">
        <div className="panel">
          <div className="label">Model versions</div>
          <ul className="vlog">{[...versions].reverse().map((v) => (
            <li key={v.version}><span className="mono b">v{v.version}</span><span>{v.note}<br />
              <span className="small muted">{v.metrics.n_train} chrome points · {v.metrics.n_absences} confirmed blanks{v.metrics.auc_holdout != null ? ` · hold-out AUC ${v.metrics.auc_holdout.toFixed(2)}` : ''} · {new Date(v.created).toLocaleString()}</span></span></li>))}</ul>
        </div>
        <div className="panel">
          <div className="label">Last update</div>
          {!diff ? <p className="muted">No update in this session yet.</p> : (
            <div>
              <p>Model v{diff.version}: hold-out AUC {diff.metrics.auc_holdout?.toFixed(2) ?? 'n/a'}, top-10% capture {Math.round((diff.metrics.capture_top10 ?? 0) * 100)}%.</p>
              <ul>{diff.changes.map((c) => <li key={c.id}><b>{c.id}</b> {c.change === 'new' ? 'is new in the top list' : `${c.change > 0 ? 'up' : 'down'} ${Math.abs(c.change)}`}</li>)}
                {diff.dropped.map((d) => <li key={d}><b>{d}</b> dropped out</li>)}
                {!diff.changes.length && !diff.dropped.length && <li>Target ranking unchanged.</li>}</ul>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
