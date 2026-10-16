import { Component, useEffect, useRef, useState } from 'react'
import { BsBoxArrowRight, BsChevronDown, BsClipboardCheck, BsDatabase, BsGeoAlt, BsGraphUpArrow, BsInboxes, BsList, BsPeople,
  BsPersonCircle, BsShieldCheck, BsX } from 'react-icons/bs'
import { reportError } from './api'
import { Logo } from './brand'
import { initials, minutes } from './util'
import { currentUser, expire, onAuth, refreshToken, signIn, signOut } from './auth'
import FieldApp from './FieldApp'
import MapView from './MapView'
import Profile from './Profile'
import { useQuery } from './query'
import Review from './Review'
import { watchSession } from './session'
import Signup from './Signup'
import Sources from './Sources'
import { takeResume, useUi } from './ui'
import Users from './Users'
import Validation from './Validation'

const PAGES = ['map', 'field', 'review', 'val', 'data', 'account', 'users']

export default function App({ config }) {
  const [user, setUser] = useState(currentUser)
  useEffect(() => onAuth(setUser), [])
  // meta polls slowly: a new model version (from another geologist's retrain) shows up without a reload
  const meta = useQuery('/api/meta', null, { poll: { min: 60000, max: 300000 } })
  const [tab, setTab] = useUi('tab', location.hash.slice(1) || 'map')
  // a link straight to a page (e.g. /#review) wins over the remembered page
  useEffect(() => { const h = location.hash.slice(1); if (PAGES.includes(h)) setTab(h) }, []) // eslint-disable-line react-hooks/exhaustive-deps
  const [lang, setLang] = useState(() => { try { return localStorage.getItem('wana.lang') || 'en' } catch { return 'en' } })
  const [planTarget, setPlanTarget] = useUi('planTarget', '')
  const [drawer, setDrawer] = useState(false)
  // sign-up is a one-off screen (also the target of the 'Create one' link on the sign-in page), never a remembered place
  const [signup, setSignup] = useState(() => location.hash === '#signup')
  const [notice, setNotice] = useState(() => {
    const q = new URLSearchParams(location.search)
    if (q.get('expired')) return 'expired'
    if (location.hash === '#welcome') return 'welcome'
    return ''
  })
  const m = meta.data
  const geo = m?.role === 'geologist'
  // pending field records, for the badge (geologists only; the review page polls the same URL)
  const recs = useQuery('/api/records', null, { enabled: geo, poll: { min: 30000, max: 180000 } })
  const pending = (recs.data || []).filter((r) => r.status === 'pending').length

  useEffect(() => { try { localStorage.setItem('wana.lang', lang) } catch { /* ignore */ } }, [lang])
  useEffect(() => { if (!signup) history.replaceState(null, '', `${location.pathname}#${tab}`) }, [tab, signup])
  useEffect(() => {
    if (user.signedIn && takeResume(user.sub)) setNotice('resumed')
    else if (user.signedIn && (notice === 'expired' || notice === 'welcome')) setNotice('')
  }, [user.signedIn, user.sub]) // eslint-disable-line react-hooks/exhaustive-deps

  if (signup && !user.signedIn) return <Signup onClose={() => setSignup(false)} />
  if (meta.error && !m) return <div className="boot"><Logo /><div className="flag">Cannot reach the Wana server: {meta.error.message}</div></div>
  if (!m) return <div className="boot"><Logo /><span className="muted">Loading Wana…</span></div>

  const NAV = [
    { k: 'map', label: 'Wana Map', icon: BsGeoAlt },
    { k: 'field', label: 'Wana Field', icon: BsClipboardCheck },
    geo && { k: 'review', label: 'Review queue', icon: BsInboxes, badge: pending },
    { k: 'val', label: 'Validation', icon: BsGraphUpArrow },
    { k: 'data', label: 'Data sources', icon: BsDatabase },
    user.signedIn && { k: 'account', label: 'Account', icon: BsPersonCircle },
    user.admin && { k: 'users', label: 'Admin · users', icon: BsPeople },
  ].filter(Boolean)
  const active = NAV.some((n) => n.k === tab) ? tab : 'map'
  const go = (k) => { setTab(k); setDrawer(false) }
  const title = NAV.find((n) => n.k === active)?.label

  return (
    <div className="shell">
      {user.signedIn && <SessionGuard config={config.session} />}
      <aside className={`side ${drawer ? 'open' : ''}`} aria-label="Main">
        <div className="side-brand"><Logo /><span>MineSense <b>Wana</b></span>
          <button className="icon-btn only-mobile" aria-label="Close menu" onClick={() => setDrawer(false)}><BsX /></button></div>
        <nav className="side-nav">
          {NAV.map(({ k, label, icon: Icon, badge }) => (
            <button key={k} className="nav-item" aria-current={active === k ? 'page' : undefined} onClick={() => go(k)}>
              <Icon aria-hidden="true" /><span>{label}</span>{badge > 0 && <span className="badge">{badge}</span>}
            </button>
          ))}
        </nav>
        <div className="side-foot">
          <div className="small muted">{m.name} · model v{m.version}{meta.stale ? ' · offline copy' : ''}</div>
          <div className="small muted">Wana shows places worth checking. It gives no mining rights.</div>
        </div>
      </aside>
      {drawer && <div className="scrim" onClick={() => setDrawer(false)} />}
      <div className="main">
        <header className="topbar">
          <button className="icon-btn only-mobile" aria-label="Open menu" onClick={() => setDrawer(true)}><BsList /></button>
          <h1 className="page-title">{title}</h1>
          <div className="seg" role="group" aria-label="Language">
            <button aria-pressed={lang === 'en'} onClick={() => setLang('en')}>EN</button>
            <button aria-pressed={lang === 'sn'} onClick={() => setLang('sn')}>SN</button>
          </div>
          {config.auth.enabled && (user.signedIn
            ? <UserMenu user={user} onAccount={() => go('account')} />
            : <div className="row nowrap"><button className="btn sm ghost hide-xs" onClick={() => setSignup(true)}>Create account</button>
              <button className="btn primary sm" onClick={signIn}>Sign in</button></div>)}
        </header>
        <div className="content">
          {notice === 'expired' && !user.signedIn && (
            <div className="callout warn" role="status"><BsShieldCheck aria-hidden="true" /><div><b>You were signed out</b> after {minutes(config.session.idle_seconds)} without activity, to keep the account safe.
              Sign in and you will be back where you left off.</div><button className="btn primary sm" onClick={signIn}>Sign in</button></div>)}
          {notice === 'resumed' && <div className="callout ok" role="status"><BsShieldCheck aria-hidden="true" /><div>Welcome back. You are where you left off.</div><button className="icon-btn" aria-label="Dismiss" onClick={() => setNotice('')}><BsX /></button></div>}
          {notice === 'welcome' && !user.signedIn && (
            <div className="callout ok" role="status"><BsShieldCheck aria-hidden="true" /><div><b>Your account is ready.</b> Sign in with your email and the password you just chose.</div>
              <button className="btn primary sm" onClick={signIn}>Sign in</button></div>)}
          {m.sample_data && (
            <div className="demo-band"><b>Sample data.</b> One or more layers are synthetic (see Data sources). Results are for testing the system, not for decisions on real ground.</div>
          )}
          <main className="view">
            <ErrorBoundary key={active}>
              {active === 'map' && <MapView meta={m} lang={lang} onPlan={(id) => { setPlanTarget(id); setTab('field') }} />}
              {active === 'field' && <FieldApp lang={lang} initialTarget={planTarget} user={user} authEnabled={config.auth.enabled} />}
              {active === 'review' && geo && <Review onRetrained={meta.refresh} />}
              {active === 'users' && user.admin && <Users me={user} />}
              {active === 'account' && user.signedIn && <Profile user={user} session={config.session} />}
              {active === 'val' && <Validation version={m.version} />}
              {active === 'data' && <Sources meta={m} />}
            </ErrorBoundary>
          </main>
        </div>
      </div>
    </div>
  )
}

function UserMenu({ user, onAccount }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return
    const close = (e) => { if (!ref.current?.contains(e.target)) setOpen(false) }
    const esc = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('pointerdown', close)
    document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('pointerdown', close); document.removeEventListener('keydown', esc) }
  }, [open])
  const role = user.admin ? 'Administrator' : user.geologist ? 'Geologist' : 'Miner'
  return (
    <div className="usermenu" ref={ref}>
      <button className="user-btn" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <span className="avatar">{initials(user.name)}</span>
        <span className="user-name hide-xs">{user.name}</span><BsChevronDown aria-hidden="true" className="hide-xs" />
      </button>
      {open && (
        <div className="menu" role="menu">
          <div className="menu-head"><b>{user.name}</b><span className="small muted">{user.email}</span><span className="role-pill">{role}</span></div>
          <button role="menuitem" onClick={() => { setOpen(false); onAccount() }}><BsPersonCircle aria-hidden="true" /> Account</button>
          <button role="menuitem" onClick={signOut}><BsBoxArrowRight aria-hidden="true" /> Log out</button>
        </div>
      )}
    </div>
  )
}

function SessionGuard({ config }) {
  const [p, setP] = useState({ phase: 'active', left: 0 })
  const [watch, setWatch] = useState(null)
  useEffect(() => {
    const w = watchSession({ idleMs: config.idle_seconds * 1000, warnMs: config.warn_seconds * 1000,
      readingMs: config.reading_seconds * 1000, onPhase: (x) => { setP(x); if (x.phase === 'expired') expire('idle') } })
    setWatch(w)
    // keep the access token fresh only while the person counts as active
    const t = setInterval(() => { if (w.policy.phase(Date.now()).phase === 'active') refreshToken() }, 60000)
    return () => { w.stop(); clearInterval(t) }
  }, [config.idle_seconds, config.warn_seconds, config.reading_seconds])
  if (p.phase !== 'warning') return null
  const s = Math.ceil(p.left / 1000)
  const frac = Math.max(0, Math.min(1, p.left / (config.warn_seconds * 1000)))
  return (
    <div className="modal-back">
      <div className="modal" role="alertdialog" aria-modal="true" aria-labelledby="sw-t" aria-describedby="sw-d">
        <div className="countdown" style={{ '--f': frac }} aria-hidden="true"><span className="mono">{s}</span></div>
        <h2 id="sw-t">Still there?</h2>
        <p id="sw-d">Your session expires in <b className="mono">{s} second{s === 1 ? '' : 's'}</b> because nothing has happened for a while.
          If it does, you will come straight back here after signing in.</p>
        <div className="row">
          <button className="btn primary" autoFocus onClick={() => { watch?.stayActive(); refreshToken() }}>Stay signed in</button>
          <button className="btn" onClick={signOut}>Log out now</button>
        </div>
      </div>
    </div>
  )
}

class ErrorBoundary extends Component {
  constructor(p) { super(p); this.state = { err: null } }
  static getDerivedStateFromError(err) { return { err } }
  componentDidCatch(err, info) { reportError(err, `render ${info.componentStack?.split('\n')[1]?.trim() || ''}`) }
  render() {
    if (!this.state.err) return this.props.children
    return <div className="flag">This part of the page failed to load. It has been reported. <button className="btn sm" onClick={() => this.setState({ err: null })}>Try again</button></div>
  }
}
