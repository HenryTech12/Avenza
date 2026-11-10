import { test, expect } from '@playwright/test'
import { settings } from './helpers'

/**
 * Smoke test against the real backend through the dev proxy. It never creates data (no enrolment).
 * Run: VITE_BACKEND_MODE=live npx vite --port 5183   then   LIVE=1 npx playwright test tests/live.spec.ts
 */
test.skip(!process.env.LIVE, 'set LIVE=1 (and start vite in live mode on :5183)')
test.use({ baseURL: 'https://localhost:5183' })

test('backend answers /healthz, /health and /config through the proxy', async ({ page }) => {
  await page.goto('/boot')
  const r = await page.evaluate(async () => {
    const get = async (p: string) => ({ status: (await fetch(p)).status, body: await (await fetch(p)).json() })
    return { healthz: await get('/healthz'), health: await get('/health'), config: await get('/config') }
  })
  expect(r.healthz).toMatchObject({ status: 200, body: { ok: true } })
  expect(r.health.body.bank).toMatchObject({ mode: expect.any(String) })
  expect(r.config.body.limits.max_amount_display).toMatch(/₦/)
  expect(r.config.body.source_accounts.length).toBeGreaterThan(0)
})

test('an unknown device token is refused (401) and sends the customer back to set up again', async ({ page }) => {
  await page.addInitScript((s) => localStorage.setItem('avenza.settings.v1', JSON.stringify(s)), { ...settings, deviceToken: 'not-a-real-token' })
  await page.goto('/settings')
  await expect(page.getByText('no longer registered')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('heading', { level: 1, name: 'Choose your language' })).toBeVisible({ timeout: 15_000 })
  const stored = await page.evaluate(() => JSON.parse(localStorage.getItem('avenza.settings.v1') ?? '{}'))
  expect(stored.deviceToken).toBeNull()
  expect(stored.onboardingComplete).toBe(false)
})

test('enrolment asks for a name before the fingerprint', async ({ page }) => {
  await page.goto('/onboarding/fingerprint')
  await expect(page.getByLabel('Your name')).toBeVisible({ timeout: 30_000 })
  await page.getByRole('button', { name: 'Register fingerprint' }).click()
  await expect(page.getByRole('alert')).toContainText('Enter your name')
})
