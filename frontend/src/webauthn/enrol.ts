import { browserSupportsWebAuthn, platformAuthenticatorIsAvailable, startRegistration } from '@simplewebauthn/browser'
import type { PublicKeyCredentialCreationOptionsJSON, RegistrationResponseJSON } from '../protocol/messages'

export type EnrolResult =
  | { ok: true; credential: RegistrationResponseJSON }
  | { ok: false; reason: 'cancelled' | 'no-authenticator' | 'already-registered' | 'error'; detail?: string }

export async function hasPlatformAuthenticator(): Promise<boolean> {
  if (!browserSupportsWebAuthn()) return false
  try {
    return await platformAuthenticatorIsAvailable()
  } catch {
    return false
  }
}

export async function enrol(options: PublicKeyCredentialCreationOptionsJSON): Promise<EnrolResult> {
  if (!(await hasPlatformAuthenticator())) return { ok: false, reason: 'no-authenticator' }
  try {
    const credential = await startRegistration({ optionsJSON: options })
    return { ok: true, credential }
  } catch (e) {
    const err = e as { name?: string; code?: string }
    if (err.code === 'ERROR_AUTHENTICATOR_PREVIOUSLY_REGISTERED') return { ok: false, reason: 'already-registered' }
    if (err.name === 'NotAllowedError' || err.code === 'ERROR_CEREMONY_ABORTED') return { ok: false, reason: 'cancelled' }
    if (err.code?.startsWith('ERROR_AUTHENTICATOR_MISSING')) return { ok: false, reason: 'no-authenticator' }
    // Never fail silently: keep the browser's own reason (shown, spoken and logged).
    console.error('[avenza] fingerprint registration failed', err.name, err.code, e)
    if (err.name === 'SecurityError' || err.code === 'ERROR_INVALID_DOMAIN' || err.code === 'ERROR_INVALID_RP_ID') {
      return { ok: false, reason: 'error', detail: 'address' }
    }
    return { ok: false, reason: 'error', detail: [err.name, err.code].filter(Boolean).join(' ') || undefined }
  }
}
