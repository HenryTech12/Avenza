import { test, type Page } from '@playwright/test'
import { openVoice, seed, addAuthenticator } from './helpers'

// Visual review helper: writes screenshots to tools/shots/. Not part of the pass/fail suite (skipped unless SHOTS=1).
test.skip(!process.env.SHOTS, 'set SHOTS=1 to capture screenshots')

const shot = (page: Page, name: string) => page.screenshot({ path: `tools/shots/${name}.png` })
const h1 = (page: Page, name: string) => page.getByRole('heading', { level: 1, name })

test('capture', async ({ page }) => {
  test.setTimeout(200_000)
  await addAuthenticator(page, 'silent')
  await page.goto('/')
  await h1(page, 'Choose your language').waitFor({ timeout: 30_000 })
  await shot(page, '1-language')
  await page.getByRole('button', { name: 'English' }).click()
  await h1(page, 'Before we start').waitFor()
  await shot(page, '2-consent')
  await page.getByRole('button', { name: 'I agree' }).click()
  await h1(page, 'Register your fingerprint').waitFor()
  await shot(page, '3-fingerprint-setup')

  const p2 = await page.context().newPage()
  await openVoice(p2, 'bank_timeout', { auth: 'silent' })
  await h1(p2, 'Listening').waitFor()
  await shot(p2, '4-listening')
  await h1(p2, 'Is this right?').waitFor({ timeout: 40_000 })
  await shot(p2, '5-readback')
  await p2.getByRole('button', { name: 'Yes, continue' }).click()
  await h1(p2, 'Approve with your fingerprint').waitFor()
  await shot(p2, '6-fingerprint')

  const p3 = await page.context().newPage()
  await openVoice(p3, 'bank_timeout', { auth: 'approve' })
  await h1(p3, 'Is this right?').waitFor({ timeout: 40_000 })
  await p3.getByRole('button', { name: 'Yes, continue' }).click()
  await h1(p3, 'Checking the final status').waitFor({ timeout: 30_000 })
  await shot(p3, '7-pending')
  await h1(p3, 'Transfer successful').waitFor({ timeout: 30_000 })
  await shot(p3, '8-settled')

  const p4 = await page.context().newPage()
  await seed(p4, 'happy_path', { theme: 'light' })
  await p4.goto('/settings')
  await h1(p4, 'Settings').waitFor({ timeout: 30_000 })
  await shot(p4, '9-settings-light')
})
