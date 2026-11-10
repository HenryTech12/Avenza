import { describe, expect, it, vi } from 'vitest'
import { createEnricher } from '../transport/liveEnrich'
import { parseNairaToKobo, parseWireMessage } from './wire'
import type { ServerMessage } from './messages'

describe('wire format', () => {
  it('parses naira text to whole kobo', () => {
    expect(parseNairaToKobo('₦5,000.00')).toBe(500000)
    expect(parseNairaToKobo('₦1,250.50')).toBe(125050)
    expect(parseNairaToKobo(null)).toBeNull()
  })

  it('maps approval.request options (plain or wrapped) and its transfer summary', () => {
    const r = parseWireMessage({
      type: 'approval.request',
      transfer_id: 'tr_1',
      options: { challenge: 'abc', rpId: 'x', allowCredentials: [] },
      transfer: { amount_kobo: 500000, bank_name: 'GTBank', account_last4: '6789', recipient: 'Aisha Bello', risk_flags: ['new_recipient_large'] },
    })
    expect(r.ok && r.msg.type === 'approval.request' && r.msg.draft).toMatchObject({
      amountKobo: 500000,
      bankName: 'GTBank',
      accountMasked: '•••• 6789',
      isNewRecipient: true,
    })
    const wrapped = parseWireMessage({ type: 'approval.request', transfer_id: 't', options: { publicKey: { challenge: 'z' } } })
    expect(wrapped.ok && wrapped.msg.type === 'approval.request' && wrapped.msg.options.challenge).toBe('z')
  })

  it('rejects unknown transfer states and options without a challenge', () => {
    expect(parseWireMessage({ type: 'state.changed', transfer_id: 't', state: 'MOVED' }).ok).toBe(false)
    expect(parseWireMessage({ type: 'approval.request', transfer_id: 't', options: {} }).ok).toBe(false)
  })

  it('enricher fetches the bank name and masked account once per transfer', async () => {
    const detail = {
      id: 'tr_1', state: 'READBACK_PLAYED', display: '', amountKobo: 500000, amountDisplay: '', bankName: 'GTBank',
      accountLast4: '6789', accountMasked: '•••• 6789', recipient: 'Aisha Bello', reference: null, createdAt: null,
      settledAt: null, failureReason: null, riskFlags: [],
    }
    const transfer = vi.fn().mockResolvedValue(detail)
    const enrich = createEnricher({ transfer })
    const first = parseWireMessage({ type: 'state.changed', transfer_id: 'tr_1', state: 'READBACK_PLAYED', amount_display: '₦5,000.00', recipient: 'Aisha Bello' })
    const out = (await enrich((first as { msg: ServerMessage }).msg)) as Extract<ServerMessage, { type: 'state.changed' }>
    expect(out.draft).toMatchObject({ bankName: 'GTBank', accountMasked: '•••• 6789', amountKobo: 500000 })
    const settled = parseWireMessage({ type: 'state.changed', transfer_id: 'tr_1', state: 'SETTLED', amount_display: '₦5,000.00', recipient: 'Aisha Bello', reference: 'AVZ-1' })
    const out2 = (await enrich((settled as { msg: ServerMessage }).msg)) as Extract<ServerMessage, { type: 'state.changed' }>
    expect(out2.draft?.reference).toBe('AVZ-1')
    expect(transfer).toHaveBeenCalledTimes(1)
  })
})
