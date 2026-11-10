import { test, expect } from '@playwright/test'
import { settings } from './helpers'

// Runs against the production build: `npm run build:mock && NO_SSL=1 npx vite preview --port 5182 (http: service workers reject self-signed certs)`
const PREVIEW = 'http://localhost:5182'

test('production build: manifest, service worker, offline app shell', async ({ page, context }) => {
  test.setTimeout(120_000)
  await page.addInitScript((s) => localStorage.setItem('avenza.settings.v1', JSON.stringify(s)), settings)
  await page.goto(`${PREVIEW}/`)
  await expect(page.getByRole('heading', { level: 1, name: 'Listening' })).toBeVisible({ timeout: 40_000 })

  const manifest = await page.evaluate(async () => {
    const href = document.querySelector('link[rel="manifest"]')?.getAttribute('href') ?? ''
    return (await fetch(href)).json()
  })
  expect(manifest).toMatchObject({ name: 'Avenza', short_name: 'Avenza', display: 'standalone', orientation: 'portrait', theme_color: '#0B1220', background_color: '#0B1220' })
  expect(manifest.icons.map((i: { sizes: string }) => i.sizes)).toEqual(expect.arrayContaining(['192x192', '512x512']))
  expect(manifest.icons.some((i: { purpose?: string }) => i.purpose === 'maskable')).toBe(true)

  await page.evaluate(() => navigator.serviceWorker.ready)
  // wait until the worker controls the page and has precached prompts, VAD files and fonts
  await page.reload()
  await expect.poll(() => page.evaluate(() => !!navigator.serviceWorker.controller), { timeout: 30_000 }).toBe(true)
  const cached = await page.evaluate(async () => {
    const urls: string[] = []
    for (const name of await caches.keys()) for (const r of await (await caches.open(name)).keys()) urls.push(new URL(r.url).pathname)
    return urls
  })
  expect(cached.some((u) => u.includes('/prompts/manifest.json'))).toBe(true)
  expect(cached.some((u) => u.includes('/vad/silero_vad_v5.onnx'))).toBe(true)
  expect(cached.some((u) => u.includes('/vad/ort-wasm-simd-threaded.wasm'))).toBe(true)
  expect(cached.some((u) => u.includes('.woff2'))).toBe(true)

  await context.setOffline(true)
  await page.reload()
  await expect(page.getByRole('heading', { level: 1, name: 'Listening' })).toBeVisible({ timeout: 30_000 })
})
