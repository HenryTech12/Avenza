import { describe, expect, it, vi } from 'vitest'

vi.mock('@simplewebauthn/browser', () => ({
  browserSupportsWebAuthn: () => true,
  platformAuthenticatorIsAvailable: async () => true,
  startRegistration: vi.fn(),
}))

import { startRegistration } from '@simplewebauthn/browser'
import { enrol } from './enrol'

const options = {} as never

describe('fingerprint registration never fails silently (phone test, 10 Nov)', () => {
  it('names an address mismatch (RP ID) instead of a generic error', async () => {
    vi.mocked(startRegistration).mockRejectedValueOnce(Object.assign(new Error('rp id'), { name: 'SecurityError', code: 'ERROR_INVALID_RP_ID' }))
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    expect(await enrol(options)).toEqual({ ok: false, reason: 'error', detail: 'address' })
  })
  it('keeps the browser reason for anything else', async () => {
    vi.mocked(startRegistration).mockRejectedValueOnce(Object.assign(new Error('x'), { name: 'InvalidStateError' }))
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    expect(await enrol(options)).toEqual({ ok: false, reason: 'error', detail: 'InvalidStateError' })
  })
  it('a dismissed prompt is still "cancelled"', async () => {
    vi.mocked(startRegistration).mockRejectedValueOnce(Object.assign(new Error('no'), { name: 'NotAllowedError' }))
    expect(await enrol(options)).toEqual({ ok: false, reason: 'cancelled' })
  })
})
