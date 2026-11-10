import { startAuthentication, WebAuthnAbortService } from '@simplewebauthn/browser'
import type { AuthenticationResponseJSON, PublicKeyCredentialRequestOptionsJSON } from '../protocol/messages'

export type ApproveResult =
  | { ok: true; assertion: AuthenticationResponseJSON }
  | { ok: false; reason: 'cancelled' | 'aborted' | 'unsupported' | 'error' }

/**
 * Real browser WebAuthn (also in mock mode, so the phone shows its fingerprint prompt).
 * Returns a result instead of throwing so the session can decide retry vs cancel.
 */
export async function approve(options: PublicKeyCredentialRequestOptionsJSON): Promise<ApproveResult> {
  try {
    const assertion = await startAuthentication({ optionsJSON: options })
    return { ok: true, assertion }
  } catch (e) {
    const err = e as { name?: string; code?: string }
    if (err.code === 'ERROR_CEREMONY_ABORTED' || err.name === 'AbortError') return { ok: false, reason: 'aborted' }
    if (err.name === 'NotAllowedError') return { ok: false, reason: 'cancelled' }
    if (err.name === 'NotSupportedError') return { ok: false, reason: 'unsupported' }
    return { ok: false, reason: 'error' }
  }
}

/** Abort a pending fingerprint prompt (state left AWAITING_BIOMETRIC, timeout, or cancel). */
export function abortApproval(): void {
  WebAuthnAbortService.cancelCeremony()
}
