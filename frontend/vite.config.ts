/// <reference types="vitest/config" />
import preact from '@preact/preset-vite'
import basicSsl from '@vitejs/plugin-basic-ssl'
import { VitePWA } from 'vite-plugin-pwa'
import { defineConfig, type ProxyOptions } from 'vite'

/** onnxruntime-web imports its .mjs from /vad/ at runtime; Vite dev appends ?import, which public files reject. */
const vadPublicImport = {
  name: 'avenza-vad-public-import',
  configureServer(server: { middlewares: { use: (fn: (req: { url?: string }, res: unknown, next: () => void) => void) => void } }) {
    server.middlewares.use((req, _res, next) => {
      if (req.url?.startsWith('/vad/')) req.url = req.url.replace(/\?import$/, '')
      next()
    })
  },
}

/**
 * `npm run dev` against the live backend without CORS: leave VITE_API_BASE_URL empty and these routes are proxied
 * to AVENZA_PROXY_TARGET with the Origin the backend allows. (Passkeys are still bound to the backend's own
 * WEBAUTHN_RP_ID, so enrolment only completes on that origin or against a local backend.)
 */
const proxyTarget = process.env.AVENZA_PROXY_TARGET ?? 'https://team18.xtradot.co'
const asBackendOrigin: NonNullable<ProxyOptions['configure']> = (proxy) => {
  proxy.on('proxyReq', (req) => req.setHeader('origin', proxyTarget))
  proxy.on('proxyReqWs', (req) => req.setHeader('origin', proxyTarget))
}
const backendRoutes = Object.fromEntries(
  ['/healthz', '/health', '/config', '/devices', '/consents', '/me', '/transfers', '/locks'].map((r) => [
    r,
    { target: proxyTarget, changeOrigin: true, secure: false, configure: asBackendOrigin },
  ]),
)

export default defineConfig({
  plugins: [
    vadPublicImport,
    preact(),
    ...(process.env.NO_SSL ? [] : [basicSsl()]),
    VitePWA({
      registerType: 'prompt',
      includeAssets: ['favicon.svg', 'icons/*.png', 'fonts/*.woff2'],
      manifest: {
        name: 'Avenza',
        short_name: 'Avenza',
        description: 'Voice banking. Speak your transfer, approve with your fingerprint.',
        display: 'standalone',
        orientation: 'portrait',
        start_url: '/',
        background_color: '#0B1220',
        theme_color: '#0B1220',
        icons: [
          { src: 'icons/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: 'icons/icon-512.png', sizes: '512x512', type: 'image/png' },
          { src: 'icons/maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,svg,png,woff2,json,mp3,wav,onnx,wasm,mjs}'],
        maximumFileSizeToCacheInBytes: 30 * 1024 * 1024,
        navigateFallback: '/index.html',
        runtimeCaching: [
          {
            urlPattern: ({ url }) => /\/(devices|consents|health)(\/|$)/.test(url.pathname),
            handler: 'NetworkFirst',
            options: { cacheName: 'api', networkTimeoutSeconds: 4 },
          },
        ],
      },
    }),
  ],
  server: {
    host: true,
    proxy: { ...backendRoutes, '/ws': { target: proxyTarget, ws: true, changeOrigin: true, secure: false, configure: asBackendOrigin } },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
