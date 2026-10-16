import { useEffect, useState } from 'react'
import { BsBoxArrowRight, BsCheckCircle, BsClipboardData, BsClock, BsHourglassSplit, BsKey, BsPencil, BsShieldLock, BsXCircle } from 'react-icons/bs'
import { api } from './api'
import { initials, minutes } from './util'
import { changePassword, signOut } from './auth'
import { setQueryData, useQuery } from './query'
import { markActivity } from './session'

const STATUS = {
  pending: { icon: BsHourglassSplit, label: 'Waiting for the geologist', cls: 'pending' },
  endorsed: { icon: BsCheckCircle, label: 'Chrome confirmed', cls: 'endorsed' },
  rejected: { icon: BsXCircle, label: 'Not chrome', cls: 'rejected' },
}

export default function Profile({ user, session }) {
  const prof = useQuery('/api/me/profile')
  // smart polling: the geologist's decisions on my records show up on their own
  const recs = useQuery('/api/me/records', null, { poll: { min: 30000, max: 300000 } })
  const p = prof.data
  const [edit, setEdit] = useState(false)
  const [f, setF] = useState({ name: '', organisation: '' })
  const [state, setState] = useState({ busy: false, err: null, ok: '' })
  useEffect(() => { if (p && !edit) setF({ name: p.name, organisation: p.organisation }) }, [p, edit])

  const save = async (e) => {
    e.preventDefault()
    setState({ busy: true, err: null, ok: '' })
    // optimistic: the card shows the new name now; the server's answer replaces it, or it is put back
    const rollback = setQueryData(prof.key, (cur) => ({ ...cur, ...f }))
    try {
      const fresh = await api.put('/api/me/profile', f)
      setQueryData(prof.key, fresh)
      setEdit(false)
      setState({ busy: false, err: null, ok: 'Saved. Your new name shows on records you send from now on.' })
      markActivity()
    } catch (err) { rollback(); setState({ busy: false, err, ok: '' }) }
  }

  const rows = recs.data || []
  const counts = { pending: 0, endorsed: 0, rejected: 0 }
  rows.forEach((r) => { counts[r.status] = (counts[r.status] || 0) + 1 })
  const role = user.admin ? 'Administrator' : user.geologist ? 'Geologist' : 'Miner'
  return (
    <div className="profile" data-reading>
      <section className="profile-hero">
        <span className="avatar xl">{initials(p?.name || user.name)}</span>
        <div>
          <h2>{p?.name || user.name}</h2>
          <div className="muted">{p?.email || user.email}{p?.organisation ? ` · ${p.organisation}` : ''}</div>
          <div className="row">{(user.roles || []).filter((r) => ['miner', 'geologist', 'admin'].includes(r)).map((r) => <span key={r} className="role-pill">{r}</span>)}</div>
        </div>
      </section>

      <div className="stat-grid">
        <Stat icon={BsClipboardData} tone="serp" n={rows.length} label="Field records sent" />
        <Stat icon={BsHourglassSplit} tone="warn" n={counts.pending} label="Waiting for review" />
        <Stat icon={BsCheckCircle} tone="ok" n={counts.endorsed} label="Chrome confirmed" />
        <Stat icon={BsXCircle} tone="bad" n={counts.rejected} label="Not chrome" />
      </div>

      <div className="profile-grid">
        <section className="panel">
          <div className="panel-head"><h3>Profile</h3>{!edit && <button className="btn sm" onClick={() => setEdit(true)}><BsPencil /> Edit</button>}</div>
          {prof.error && !p && <div className="flag">{prof.error.message}</div>}
          {edit ? (
            <form className="form" onSubmit={save}>
              <label htmlFor="pf-name">Full name</label>
              <input id="pf-name" value={f.name} minLength={2} maxLength={80} required onChange={(e) => setF({ ...f, name: e.target.value })} />
              <label htmlFor="pf-org">Cooperative or organisation</label>
              <input id="pf-org" value={f.organisation} maxLength={120} onChange={(e) => setF({ ...f, organisation: e.target.value })} />
              {state.err && <div className="flag" role="alert">{state.err.message}</div>}
              <div className="row"><button className="btn primary" disabled={state.busy}>{state.busy ? 'Saving…' : 'Save'}</button>
                <button type="button" className="btn" onClick={() => { setEdit(false); setState({ busy: false, err: null, ok: '' }) }}>Cancel</button></div>
            </form>
          ) : (
            <dl className="facts">
              <dt>Name</dt><dd>{p?.name || '—'}</dd>
              <dt>Email</dt><dd>{p?.email || user.email} {p?.email_verified && <span className="ok-text"><BsCheckCircle /> verified</span>}</dd>
              <dt>Organisation</dt><dd>{p?.organisation || <span className="muted">not set</span>}</dd>
              <dt>Role</dt><dd>{role}{!user.geologist && <span className="small muted"> · an administrator grants geologist access</span>}</dd>
              <dt>Member since</dt><dd>{p?.created ? new Date(p.created).toLocaleDateString() : '—'}</dd>
            </dl>
          )}
          {state.ok && <div className="toast" role="status">{state.ok}</div>}
        </section>

        <section className="panel">
          <div className="panel-head"><h3>Security</h3></div>
          <ul className="sec-list">
            <li><BsKey /><div><b>Password</b><div className="small muted">Change it on the secure Wana sign-in page.</div></div>
              <button className="btn sm" onClick={changePassword}>Change</button></li>
            <li><BsClock /><div><b>Automatic sign-out</b><div className="small muted">After {minutes(session.idle_seconds)} without activity, with a {session.warn_seconds}-second warning.
              Reading a card or page counts as activity for up to {minutes(session.reading_seconds)}.</div></div></li>
            <li><BsShieldLock /><div><b>This device</b><div className="small muted">Signing out removes your cached data from this browser.</div></div>
              <button className="btn sm" onClick={signOut}><BsBoxArrowRight /> Log out</button></li>
          </ul>
        </section>
      </div>

      <section className="panel">
        <div className="panel-head"><h3>My field records</h3>{recs.validating && <span className="small muted">checking…</span>}</div>
        {recs.loading && <p className="muted">Loading…</p>}
        {!recs.loading && rows.length === 0 && <p className="muted">You have not sent any field records yet. Use Wana Field at a target to record what you see.</p>}
        <ul className="rec-list">
          {rows.map((r) => {
            const s = STATUS[r.status] || STATUS.pending
            const Icon = s.icon
            return (
              <li key={r.id}>
                <span className={`rec-ico ${s.cls}`}><Icon /></span>
                <div><b className="mono">{r.sample_no}</b> · {r.target_id || 'new location'}
                  <div className="small muted">{new Date(r.created_at).toLocaleString()}{r.notes ? ` · ${r.notes}` : ''}</div></div>
                <div className="rec-status"><span className={`st ${s.cls}`}>{s.label}</span>
                  {r.lab_cr2o3 != null && <div className="small muted">Lab: {r.lab_cr2o3}% Cr₂O₃</div>}
                  {r.used_in_version != null && <div className="small muted">Used in map v{r.used_in_version}</div>}</div>
              </li>
            )
          })}
        </ul>
      </section>
    </div>
  )
}

function Stat({ icon: Icon, tone, n, label }) {
  return <div className="stat"><span className={`stat-ico ${tone}`}><Icon /></span><div className="stat-n">{n}</div><div className="stat-l">{label}</div></div>
}
