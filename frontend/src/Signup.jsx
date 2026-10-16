import { useState } from 'react'
import { BsArrowLeft, BsCheck2, BsEnvelopeCheck } from 'react-icons/bs'
import { api } from './api'
import { signIn } from './auth'
import { Logo } from './brand'

const POINTS = ['Ranks chrome ground from maps, satellites and known workings', 'Explains every target in English and Shona',
  'Works offline in the field', 'A geologist checks every result']

/** The split auth layout shared with the Keycloak sign-in theme (infra/keycloak/themes/wana). */
export function AuthSplit({ children }) {
  return (
    <div className="auth">
      <section className="auth-form">
        <div className="auth-inner">
          <div className="auth-brand"><Logo /><span>MineSense <b>Wana</b></span></div>
          {children}
        </div>
      </section>
      <section className="auth-hero" aria-hidden="true">
        <img src={`${import.meta.env.BASE_URL}hero.svg`} alt="" />
        <div className="glass">
          <h2>Better ground. Less guesswork.</h2>
          <p>Wana brings a century of geological maps, satellite imagery and known workings into one map of where chrome is most likely, so small-scale miners check the best ground first.</p>
          <ul>{POINTS.map((p) => <li key={p}><BsCheck2 /> {p}</li>)}</ul>
        </div>
      </section>
    </div>
  )
}

// Sign-up asks only for a name and an email. The email carries a one-time link to verify the address and
// choose a password, so we never handle a password here.
export default function Signup({ onClose }) {
  const [f, setF] = useState({ name: '', email: '', organisation: '', accept: false })
  const [state, setState] = useState({ busy: false, done: '', err: null })
  const submit = async (e) => {
    e.preventDefault()
    setState({ busy: true, done: '', err: null })
    try {
      const r = await api.post('/api/auth/signup', f, { retries: 1 })
      setState({ busy: false, done: r.message, err: null })
    } catch (err) { setState({ busy: false, done: '', err }) }
  }
  return (
    <AuthSplit>
      {state.done ? (
        <>
          <h1 className="auth-title">Check your email</h1>
          <div className="auth-card" role="status">
            <div className="sent-icon"><BsEnvelopeCheck /></div>
            <p><b>{f.email}</b></p>
            <p className="muted">{state.done}</p>
            <p className="small muted">The link lets you choose your password. Nothing arrived? Look in spam, or try again in a few minutes.</p>
            <button className="btn primary" onClick={onClose}>Back to the map</button>
          </div>
        </>
      ) : (
        <>
          <h1 className="auth-title">Create your account</h1>
          <p className="auth-sub">Free for miners and cooperatives. We email you a link to choose your password.</p>
          <form onSubmit={submit} className="auth-card form" noValidate>
            <label htmlFor="su-name">Full name</label>
            <input id="su-name" autoComplete="name" required minLength={2} maxLength={80} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
            <label htmlFor="su-email">Email</label>
            <input id="su-email" type="email" autoComplete="email" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
            <label htmlFor="su-org">Cooperative or organisation <span className="muted">(optional)</span></label>
            <input id="su-org" maxLength={120} value={f.organisation} onChange={(e) => setF({ ...f, organisation: e.target.value })} />
            <label className="check"><input type="checkbox" checked={f.accept} onChange={(e) => setF({ ...f, accept: e.target.checked })} />
              <span>I understand that Wana shows places worth checking. It does not prove chrome is there and gives no right to mine.</span></label>
            {state.err && <div className={`flag ${state.err.kind === 'user' ? 'info' : ''}`} role="alert">{state.err.message}</div>}
            <div><button className="btn primary lg" type="submit" disabled={state.busy || !f.accept}>{state.busy ? 'Sending…' : 'Send me the link'}</button></div>
            <p className="small">Already have an account? <button type="button" className="link" onClick={signIn}>Log in</button></p>
          </form>
          <button className="link back" onClick={onClose}><BsArrowLeft /> Back to the map</button>
        </>
      )}
    </AuthSplit>
  )
}
