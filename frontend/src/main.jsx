import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import { syncOutbox } from './outbox'

createRoot(document.getElementById('root')).render(<StrictMode><App /></StrictMode>)
// try to send anything left on the phone from a previous session
syncOutbox()
