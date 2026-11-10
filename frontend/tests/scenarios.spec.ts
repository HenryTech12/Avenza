import { test, expect, type Page } from '@playwright/test'
import { openVoice } from './helpers'

const status = (page: Page, name: string | RegExp) => page.getByRole('heading', { level: 1, name })
const readback = (page: Page) => status(page, 'Is this right?')
const LONG = 150_000

function watchErrors(page: Page) {
  const errors: string[] = []
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
  page.on('pageerror', (e) => errors.push(e.message))
  return errors
}

test.describe('mock scenarios end to end', () => {
  test('happy_path: speech, read-back, yes, fingerprint, settled, back to listening', async ({ page }) => {
    const errors = watchErrors(page)
    await openVoice(page, 'happy_path')
    await expect(status(page, 'Listening')).toBeVisible()
    await expect(readback(page)).toBeVisible({ timeout: 40_000 })
    await expect(page.getByText('Aisha Bello', { exact: true })).toBeVisible()
    await expect(page.getByText('₦5,000.00').first()).toBeVisible()
    await expect(page.getByText('five thousand naira', { exact: true })).toBeVisible()
    await expect(page.getByText('Verified by your bank').first()).toBeVisible()
    await expect(page.getByRole('button', { name: /send|pay/i })).toHaveCount(0) // rule 1: never a Send button
    await page.getByRole('button', { name: 'Yes, continue' }).click()
    await expect(status(page, 'Transfer successful')).toBeVisible({ timeout: 30_000 })
    await expect(page.getByText(/AVZ\d+/)).toBeVisible()
    await expect(status(page, 'Listening')).toBeVisible({ timeout: 30_000 })
    expect(errors).toEqual([])
  })

  test('say_no: read-back then No cancels', async ({ page }) => {
    await openVoice(page, 'say_no')
    await expect(readback(page)).toBeVisible({ timeout: 40_000 })
    await page.getByRole('button', { name: 'No, cancel' }).click()
    await expect(status(page, 'Cancelled. No money moved.')).toBeVisible()
    await expect(status(page, 'Listening')).toBeVisible({ timeout: 20_000 })
  })

  test('repeat_then_yes by voice alone (no taps): repeat, yes, fingerprint, settled', async ({ page }) => {
    test.setTimeout(LONG)
    await openVoice(page, 'repeat_then_yes')
    await expect(readback(page)).toBeVisible({ timeout: 40_000 })
    // the next two spoken replies are the scripted "repeat" then "yes"
    await expect(status(page, 'Transfer successful')).toBeVisible({ timeout: 130_000 })
  })

  test('unclear_twice: two unclear replies cancel', async ({ page }) => {
    test.setTimeout(LONG)
    await openVoice(page, 'unclear_twice')
    await expect(readback(page)).toBeVisible({ timeout: 40_000 })
    await expect(status(page, 'Cancelled. No money moved.')).toBeVisible({ timeout: 120_000 })
  })

  test('fingerprint_fail: retry once, then cancelled', async ({ page }) => {
    await openVoice(page, 'fingerprint_fail', { auth: 'fail' })
    await expect(readback(page)).toBeVisible({ timeout: 40_000 })
    await page.getByRole('button', { name: 'Yes, continue' }).click()
    await expect(status(page, 'Approve with your fingerprint')).toBeVisible()
    await page.getByRole('button', { name: 'Try again' }).click()
    await expect(status(page, 'Cancelled. No money moved.')).toBeVisible({ timeout: 20_000 })
  })

  test('fingerprint_timeout: server expires the transfer', async ({ page }) => {
    test.setTimeout(LONG)
    await openVoice(page, 'fingerprint_timeout', { auth: 'silent' })
    await expect(readback(page)).toBeVisible({ timeout: 40_000 })
    await page.getByRole('button', { name: 'Yes, continue' }).click()
    await expect(status(page, 'Approve with your fingerprint')).toBeVisible()
    await expect(page.getByRole('timer')).toBeVisible()
    await expect(status(page, 'Time ran out. No money moved.')).toBeVisible({ timeout: 40_000 })
  })

  test('bank_timeout: pending, then settled', async ({ page }) => {
    await openVoice(page, 'bank_timeout')
    await expect(readback(page)).toBeVisible({ timeout: 40_000 })
    await page.getByRole('button', { name: 'Yes, continue' }).click()
    await expect(status(page, 'Checking the final status')).toBeVisible({ timeout: 30_000 })
    await expect(status(page, 'Transfer successful')).toBeVisible({ timeout: 30_000 })
  })

  test('bank_failed: failed, money has not moved', async ({ page }) => {
    await openVoice(page, 'bank_failed')
    await expect(readback(page)).toBeVisible({ timeout: 40_000 })
    await page.getByRole('button', { name: 'Yes, continue' }).click()
    await expect(status(page, 'Transfer failed')).toBeVisible({ timeout: 30_000 })
    await expect(page.getByText('Your money has not moved.').first()).toBeVisible()
    await expect(page.getByText('Recipient bank unavailable')).toBeVisible()
  })

  test('provider_down: spoken-error sheet, money has not moved', async ({ page }) => {
    await openVoice(page, 'provider_down')
    const sheet = page.getByRole('alertdialog')
    await expect(sheet).toBeVisible({ timeout: 40_000 })
    await expect(sheet).toContainText('Your money has not moved.')
    await sheet.getByRole('button', { name: 'Close' }).click()
    await expect(sheet).toBeHidden()
  })

  test('ws_drop: reconnecting sheet during fingerprint, then recovers', async ({ page }) => {
    test.setTimeout(LONG)
    await openVoice(page, 'ws_drop', { auth: 'silent' })
    await expect(readback(page)).toBeVisible({ timeout: 40_000 })
    await page.getByRole('button', { name: 'Yes, continue' }).click()
    await expect(status(page, 'Approve with your fingerprint')).toBeVisible()
    await expect(page.getByRole('alertdialog')).toContainText('Reconnecting', { timeout: 15_000 })
    await expect(page.getByRole('alertdialog')).toBeHidden({ timeout: 15_000 })
    await expect(status(page, 'Approve with your fingerprint')).toBeVisible()
  })

  test('slow_network: still completes', async ({ page }) => {
    test.setTimeout(LONG)
    await openVoice(page, 'slow_network')
    await expect(readback(page)).toBeVisible({ timeout: 60_000 })
    await page.getByRole('button', { name: 'Yes, continue' }).click()
    await expect(status(page, 'Transfer successful')).toBeVisible({ timeout: 60_000 })
  })

  test('new_recipient_large: scam pause warning (flag scamPause)', async ({ page }) => {
    await openVoice(page, 'new_recipient_large', { query: '?flags=scamPause' })
    await expect(status(page, 'New recipient, large amount')).toBeVisible({ timeout: 40_000 })
    await expect(page.getByRole('timer')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Cancel this transfer' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Yes, continue' })).toHaveCount(0)
    await expect(readback(page)).toBeVisible({ timeout: 15_000 })
    await expect(page.getByText('New recipient', { exact: true })).toBeVisible()
  })
})
