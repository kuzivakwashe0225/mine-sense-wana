import { useState } from 'react'
import { api } from './api'
import { setQueryData, useQuery } from './query'
import { markActivity } from './session'

export default function Users({ me }) {
  const q = useQuery('/api/admin/users', null, { poll: { min: 30000, max: 180000 } })
  const [err, setErr] = useState(null)
  const [msg, setMsg] = useState('')

  const toggle = async (u, role) => {
    const grant = !u.roles.includes(role)
    setErr(null)
    // optimistic: flip the badge now, put it back if the server says no
    const rollback = setQueryData(q.key, (rows) => rows.map((r) => (r.id === u.id
      ? { ...r, roles: grant ? [...r.roles, role].sort() : r.roles.filter((x) => x !== role) } : r)))
    try { await api.post(`/api/admin/users/${u.id}/roles`, { role, grant }); markActivity() } catch (e) { rollback(); setErr(e) }
  }
  const invite = async (u) => {
    setErr(null); setMsg('')
    try { await api.post(`/api/admin/users/${u.id}/invite`); setMsg(`A new set-password link was sent to ${u.email}.`); markActivity() } catch (e) { setErr(e) }
  }
  return (
    <div data-reading>
      <h2>Accounts</h2>
      <p className="muted">Everyone who signs up is a miner. Grant <b>geologist</b> to people who review field records and need exact locations; <b>admin</b> to people who manage accounts.</p>
      {err && <div className="flag" role="alert">{err.message}</div>}
      {msg && <div className="toast" role="status">{msg}</div>}
      {q.error && !q.data && <div className="flag">{q.error.message}</div>}
      <div className="tablewrap"><table>
        <thead><tr><th>Name</th><th>Email</th><th>Organisation</th><th>Status</th><th>Geologist</th><th>Admin</th><th /></tr></thead>
        <tbody>
          {q.loading && <tr><td colSpan={7} className="muted">Loading…</td></tr>}
          {(q.data || []).map((u) => (
            <tr key={u.id}>
              <td>{u.name || '—'}</td><td className="mono small">{u.email}</td><td>{u.organisation || ''}</td>
              <td><span className={`st ${u.needs_password ? 'pending' : 'endorsed'}`}>{u.needs_password ? 'invited' : 'active'}</span></td>
              <td><input type="checkbox" aria-label={`Geologist: ${u.email}`} checked={u.roles.includes('geologist')} onChange={() => toggle(u, 'geologist')} /></td>
              <td><input type="checkbox" aria-label={`Admin: ${u.email}`} checked={u.roles.includes('admin')} disabled={u.id === me.sub} onChange={() => toggle(u, 'admin')} /></td>
              <td>{u.needs_password && <button className="btn sm" onClick={() => invite(u)}>Resend link</button>}</td>
            </tr>
          ))}
        </tbody>
      </table></div>
    </div>
  )
}
