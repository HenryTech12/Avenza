import { describe, expect, it } from 'vitest'
import { parseServerMessage } from './schemas'

describe('parseServerMessage', () => {
  it('accepts valid messages', () => {
    expect(parseServerMessage({ type: 'listening' }).ok).toBe(true)
    expect(parseServerMessage(JSON.stringify({ type: 'transcript.final', text: 'hi' })).ok).toBe(true)
    const r = parseServerMessage({
      type: 'state.changed',
      transferId: 't',
      state: 'READBACK_PLAYED',
      draft: { amountKobo: 500000, recipientName: 'A', bankName: 'B', accountMasked: '•••• 1' },
    })
    expect(r.ok).toBe(true)
  })
  it('ignores unknown types', () => {
    const r = parseServerMessage({ type: 'something.new', x: 1 })
    expect(r).toEqual({ ok: false, reason: 'unknown-type' })
  })
  it('drops malformed messages without throwing', () => {
    expect(parseServerMessage('not json')).toMatchObject({ ok: false, reason: 'malformed' })
    expect(parseServerMessage(null)).toMatchObject({ ok: false, reason: 'malformed' })
    expect(parseServerMessage({ type: 'state.changed', transferId: 't', state: 'NOPE' })).toMatchObject({ ok: false, reason: 'malformed' })
    expect(parseServerMessage({ type: 'state.changed', transferId: 't', state: 'SETTLED', draft: { amountKobo: 1.5 } })).toMatchObject({
      ok: false,
      reason: 'malformed',
    })
    expect(parseServerMessage({ type: 'error', code: 'x' })).toMatchObject({ ok: false, reason: 'malformed' })
  })
  it('accepts approval.request with extra WebAuthn fields', () => {
    const r = parseServerMessage({ type: 'approval.request', transferId: 't', options: { challenge: 'abc', rpId: 'x', timeout: 1 } })
    expect(r.ok).toBe(true)
  })
})
