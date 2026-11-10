import { generateKeyPairSync, randomBytes } from 'node:crypto'
import type { Page, CDPSession } from '@playwright/test'

export const settings = {
  language: 'en',
  consentId: 'con_test',
  deviceToken: 'dev_test',
  onboardingComplete: true,
  theme: 'dark',
  highContrast: false,
}

export type AuthMode = 'approve' | 'fail' | 'silent'

/**
 * Chrome virtual authenticator with a pre-registered resident credential, so the mock fingerprint step works.
 * approve: succeeds. fail: user verification fails (NotAllowedError). silent: never responds.
 */
export async function addAuthenticator(page: Page, mode: AuthMode = 'approve'): Promise<CDPSession> {
  const cdp = await page.context().newCDPSession(page)
  await cdp.send('WebAuthn.enable')
  const { authenticatorId } = await cdp.send('WebAuthn.addVirtualAuthenticator', {
    options: {
      protocol: 'ctap2',
      transport: 'internal',
      hasResidentKey: true,
      hasUserVerification: true,
      isUserVerified: mode === 'approve',
      automaticPresenceSimulation: mode !== 'silent',
    },
  })
  const { privateKey } = generateKeyPairSync('ec', { namedCurve: 'P-256' })
  await cdp.send('WebAuthn.addCredential', {
    authenticatorId,
    credential: {
      credentialId: randomBytes(16).toString('base64'),
      isResidentCredential: true,
      rpId: 'localhost',
      privateKey: privateKey.export({ type: 'pkcs8', format: 'der' }).toString('base64'),
      userHandle: randomBytes(8).toString('base64'),
      signCount: 0,
    },
  })
  return cdp
}

/** Seed persisted onboarding and pick a mock scenario before the app loads. */
export async function seed(page: Page, scenario: string, extra: Record<string, unknown> = {}) {
  await page.addInitScript(
    ([s, sc, ex]) => {
      localStorage.setItem('avenza.settings.v1', JSON.stringify({ ...(s as object), ...(ex as object) }))
      sessionStorage.setItem('avenza.devOverride', JSON.stringify({ MOCK_SCENARIO: sc }))
    },
    [settings, scenario, extra] as const,
  )
}

export async function openVoice(page: Page, scenario: string, opts: { auth?: AuthMode; query?: string } = {}) {
  await seed(page, scenario)
  const cdp = await addAuthenticator(page, opts.auth ?? 'approve')
  await page.goto(`/${opts.query ?? ''}`)
  return cdp
}
