import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import './shell.css'
import { api, reportError } from './api'
import App from './App.jsx'
import { initAuth } from './auth'
import { syncOutbox } from './outbox'

window.addEventListener('error', (e) => reportError(e.error || e.message, 'window.onerror'))
window.addEventListener('unhandledrejection', (e) => reportError(e.reason, 'unhandledrejection'))

const OFFLINE_CONFIG = { auth: { enabled: false }, session: { idle_seconds: 900, warn_seconds: 60, reading_seconds: 1800 } }

async function start() {
  const root = createRoot(document.getElementById('root'))
  let config
  try {
    config = await api.get('/api/config')
    try { localStorage.setItem('wana.config', JSON.stringify(config)) } catch { /* blocked */ }
  } catch {
    // offline start (field phone): last known config, else visitor mode; the outbox keeps records until signed in
    try { config = JSON.parse(localStorage.getItem('wana.config')) } catch { /* bad value */ }
    config = config || OFFLINE_CONFIG
  }
  await initAuth(config.auth)
  root.render(<StrictMode><App config={config} /></StrictMode>)
  syncOutbox() // send anything left on the phone from a previous session
}
start()
