import { test, expect, type Page } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { addAuthenticator, openVoice, seed } from './helpers'

async function axe(page: Page, label: string) {
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  const bad = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
  expect(bad.map((v) => `${label}: ${v.id} (${v.impact}) ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`)).toEqual([])
}

const heading = (page: Page, name: string) => page.getByRole('heading', { level: 1, name })

test.describe('onboarding', () => {
  test('language, consent, fingerprint, voice (with axe on each screen)', async ({ page }) => {
    await addAuthenticator(page, 'approve')
    await page.goto('/')
    await expect(heading(page, 'Choose your language')).toBeVisible({ timeout: 30_000 })
    await axe(page, 'language')
    await page.getByRole('button', { name: 'English' }).click()
    await expect(heading(page, 'Before we start')).toBeVisible()
    await axe(page, 'consent')
    await page.getByRole('button', { name: 'Not now' }).click()
    await expect(page.getByRole('alertdialog')).toContainText('cannot work without')
    await axe(page, 'consent-sheet')
    await page.getByRole('button', { name: 'Close' }).click()
    await page.getByRole('button', { name: 'I agree' }).click()
    await expect(heading(page, 'Register your fingerprint')).toBeVisible()
    await axe(page, 'fingerprint-setup')
    await page.getByLabel('Your name').fill('Test Customer')
    await page.getByRole('button', { name: 'Register fingerprint' }).click()
    await expect(heading(page, 'Listening')).toBeVisible({ timeout: 30_000 })
    const stored = await page.evaluate(() => JSON.parse(localStorage.getItem('avenza.settings.v1') ?? '{}'))
    expect(stored.onboardingComplete).toBe(true)
    expect(stored.consentId).toBeTruthy()
    expect(stored.deviceToken).toBeTruthy()
    // privacy: nothing but the allowed keys is persisted
    expect(Object.keys(stored).sort()).toEqual(['consentId', 'deviceToken', 'highContrast', 'language', 'onboardingComplete', 'theme'])
    expect(await page.evaluate(() => indexedDB.databases?.().then((d) => d.length))).toBe(0)
  })
})

test.describe('axe on app screens and panels', () => {
  test('voice: listening, readback, fingerprint, result, cancelled', async ({ page }) => {
    test.setTimeout(120_000)
    await openVoice(page, 'happy_path', { auth: 'silent' })
    await expect(heading(page, 'Listening')).toBeVisible()
    await axe(page, 'listening')
    await expect(heading(page, 'Is this right?')).toBeVisible({ timeout: 40_000 })
    await axe(page, 'readback')
    await page.getByRole('button', { name: 'Yes, continue' }).click()
    await expect(heading(page, 'Approve with your fingerprint')).toBeVisible()
    await axe(page, 'fingerprint')
    await page.getByRole('button', { name: 'Cancel' }).click()
    await expect(heading(page, 'Cancelled. No money moved.')).toBeVisible()
    await axe(page, 'cancelled')
  })

  test('voice: settled result and failed result', async ({ page }) => {
    await openVoice(page, 'happy_path')
    await expect(heading(page, 'Is this right?')).toBeVisible({ timeout: 40_000 })
    await page.getByRole('button', { name: 'Yes, continue' }).click()
    await expect(heading(page, 'Transfer successful')).toBeVisible({ timeout: 30_000 })
    await axe(page, 'settled')
  })

  test('voice: failed + error sheet', async ({ page }) => {
    await openVoice(page, 'bank_failed')
    await expect(heading(page, 'Is this right?')).toBeVisible({ timeout: 40_000 })
    await page.getByRole('button', { name: 'Yes, continue' }).click()
    await expect(heading(page, 'Transfer failed')).toBeVisible({ timeout: 30_000 })
    await axe(page, 'failed')
  })

  test('voice: provider error sheet', async ({ page }) => {
    await openVoice(page, 'provider_down')
    await expect(page.getByRole('alertdialog')).toBeVisible({ timeout: 40_000 })
    await axe(page, 'error-sheet')
  })

  test('settings, history, lock, in dark, light and high contrast', async ({ page }) => {
    test.setTimeout(240_000)
    for (const [theme, highContrast] of [['dark', false], ['light', false], ['dark', true], ['light', true]] as const) {
      await seed(page, 'happy_path', { theme, highContrast })
      await page.goto('/settings')
      await expect(heading(page, 'Settings')).toBeVisible({ timeout: 30_000 })
      await axe(page, `settings ${theme} hc=${highContrast}`)
      await page.goto('/history')
      await expect(heading(page, 'History')).toBeVisible({ timeout: 30_000 })
      await axe(page, `history ${theme} hc=${highContrast}`)
      await page.goto('/lock')
      await expect(heading(page, 'Transfers are locked')).toBeVisible({ timeout: 30_000 })
      await axe(page, `lock ${theme} hc=${highContrast}`)
    }
  })

  test('voice listening in light and high contrast', async ({ page }) => {
    test.setTimeout(120_000)
    for (const [theme, highContrast] of [['light', false], ['dark', true], ['light', true]] as const) {
      await seed(page, 'happy_path', { theme, highContrast })
      await page.goto('/')
      await expect(heading(page, 'Listening')).toBeVisible({ timeout: 30_000 })
      await axe(page, `listening ${theme} hc=${highContrast}`)
    }
  })
})
