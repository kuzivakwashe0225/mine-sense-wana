import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// `vite build --mode mobile` builds the bundle for the Android app (mobile/): no service worker there,
// the app shell is already on the phone and the API lives at VITE_API_BASE.
export default defineConfig(({ mode }) => ({
  base: mode === 'mobile' ? './' : '/',
  plugins: [
    react(),
    mode !== 'mobile' && VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['icon-192.png', 'icon-512.png'],
      manifest: {
        name: 'MineSense Wana',
        short_name: 'Wana',
        description: 'Chrome prospectivity map and field app for small-scale miners',
        theme_color: '#2C6A54',
        background_color: '#ECEFEA',
        display: 'standalone',
        start_url: '/',
        icons: [
          { src: '/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any maskable' },
        ],
      },
      workbox: {
        // Keycloak pages (sign-in, email links) and the silent sign-in check must always come from the
        // network: answering them with the cached app shell would show a blank page
        navigateFallbackDenylist: [/^\/api\//, /^\/auth\//, /^\/silent-check-sso/],
        maximumFileSizeToCacheInBytes: 4 * 1024 * 1024,
        runtimeCaching: [
          // public map images only; the geologist's full-resolution ranking is never stored in a shared cache.
          // API answers are not cached here: they depend on who is signed in, so query.js keeps them per user.
          { urlPattern: ({ url }) => url.pathname.startsWith('/api/files/') && !url.pathname.endsWith('/rank.png'), handler: 'CacheFirst',
            options: { cacheName: 'wana-overlays', expiration: { maxEntries: 60 } } },
          { urlPattern: ({ url }) => url.hostname === 'tile.openstreetmap.org', handler: 'CacheFirst',
            options: { cacheName: 'osm-tiles', expiration: { maxEntries: 3000, maxAgeSeconds: 60 * 60 * 24 * 60 } } },
        ],
      },
    }),
  ],
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
  test: { environment: 'jsdom' },
}))
