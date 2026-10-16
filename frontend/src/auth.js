// Sign-in with Keycloak (OpenID Connect, authorization code + PKCE). Tokens stay in memory; nothing secret is
// written to localStorage. A page refresh keeps the person signed in through Keycloak's SSO cookie
// (check-sso), until they press "Sign out" or the session expires.
import Keycloak from 'keycloak-js'
import { setAuthHooks } from './api'
import { clearPersisted, setScope } from './query'
import { clearSessionClock } from './session'
import { dropResume, saveResume } from './ui'

const native = () => !!window.Capacitor?.isNativePlatform?.()
// the Android app is served from https://localhost; the web app from its own origin
const appUrl = () => (native() ? 'https://localhost/' : `${location.origin}/`)

let kc = null
let listeners = new Set()
let user = { signedIn: false }
const emit = () => listeners.forEach((fn) => fn(user))
export const onAuth = (fn) => { listeners.add(fn); fn(user); return () => listeners.delete(fn) }
export const currentUser = () => user

function fromToken() {
  const t = kc.tokenParsed || {}
  const roles = t.realm_access?.roles || []
  user = { signedIn: true, sub: t.sub, email: t.email, name: t.name || t.preferred_username || t.email,
    roles, geologist: roles.includes('geologist') || roles.includes('admin'), admin: roles.includes('admin') }
  setScope(t.sub)
  emit()
}

const BROADCAST = 'wana.signout'

export async function initAuth(cfg) {
  setAuthHooks({ token: async () => '', authLost: () => {} })
  if (!cfg?.enabled) { setScope('anon'); return user }
  kc = new Keycloak({ url: cfg.url, realm: cfg.realm, clientId: cfg.client_id })
  kc.onAuthRefreshError = () => expire('refresh-failed')
  kc.onAuthLogout = () => expire('logged-out-elsewhere')
  let ok = false
  try {
    ok = await kc.init({
      onLoad: 'check-sso', pkceMethod: 'S256', responseMode: 'query', checkLoginIframe: false,
      // same-origin iframe on the web; the Android WebView blocks third-party cookies, so it does a quick redirect
      silentCheckSsoRedirectUri: native() ? undefined : `${location.origin}/silent-check-sso.html`,
      messageReceiveTimeout: 8000,
    })
  } catch {
    ok = false // offline or Keycloak unreachable: carry on as a visitor; the field outbox still works
  }
  setAuthHooks({
    token: async ({ force } = {}) => {
      if (!kc?.authenticated) return ''
      try { await kc.updateToken(force ? -1 : 30) } catch { return '' }
      return kc.token
    },
    authLost: () => expire('rejected'),
  })
  if (ok) fromToken()
  else { setScope('anon'); emit() }
  // signed out in another tab of this browser: follow
  window.addEventListener('storage', (e) => { if (e.key === BROADCAST && e.newValue && user.signedIn) { user = { signedIn: false }; emit(); location.reload() } })
  return user
}

export function signIn() {
  return kc?.login({ redirectUri: appUrl() })
}

/** Deliberate sign-out: forget this user's place and cached data on this device. */
export function signOut() {
  if (!kc) return
  dropResume()
  clearPersisted(user.sub)
  clearSessionClock()
  // older app versions cached API answers in the service worker without regard to the user
  if (window.caches) caches.delete('wana-api').catch(() => {})
  try { localStorage.setItem(BROADCAST, String(Date.now())) } catch { /* blocked */ }
  return kc.logout({ redirectUri: appUrl() })
}

/** Session ended for idleness (or the server refused the token): save where they were, end the SSO session. */
export function expire(reason = 'idle') {
  if (!kc?.authenticated) return
  saveResume(user.sub)
  clearSessionClock()
  try { sessionStorage.setItem('wana.expired', reason) } catch { /* blocked */ }
  return kc.logout({ redirectUri: `${appUrl()}?expired=1` }).catch(() => location.assign(`${appUrl()}?expired=1`))
}

/** Keep the access token fresh while the person is active (the session watcher calls this). */
export function refreshToken() {
  if (kc?.authenticated) kc.updateToken(60).catch(() => {})
}

/** Current access token, synchronously (for map tile requests). Empty when signed out. */
export const currentToken = () => (kc?.authenticated ? kc.token : '')

/** Keycloak's own change-password screen (same Wana design), then back to the account page. */
export function changePassword() {
  return kc?.login({ action: 'UPDATE_PASSWORD', redirectUri: appUrl() })
}

/** Sending records needs an account, except in laptop mode where the server has no sign-in configured. */
export const signInRequired = () => !!kc
