import { describe, expect, it } from 'vitest'
import { initialState, reduce, type MachineEvent, type MachineState } from './machine'
import type { TransferDraft } from '../protocol/messages'

const draft: TransferDraft = { amountKobo: 500000, recipientName: 'Aisha Bello', bankName: 'GTBank', accountMasked: '•••• 4821' }
const run = (events: MachineEvent[], s: MachineState = initialState) => events.reduce(reduce, s)
const sc = (state: Extract<MachineEvent, { type: 'STATE_CHANGED' }>['state'], d?: TransferDraft): MachineEvent => ({
  type: 'STATE_CHANGED',
  transferId: 't1',
  state,
  draft: d,
})

describe('machine: audio-only states', () => {
  it('listening -> hearing -> checking', () => {
    expect(run([{ type: 'VAD_START' }]).ui).toBe('hearing')
    expect(run([{ type: 'VAD_START' }, { type: 'VAD_END' }]).ui).toBe('checking')
  })
  it('server listening returns checking/hearing to listening', () => {
    expect(run([{ type: 'VAD_START' }, { type: 'VAD_END' }, { type: 'SERVER_LISTENING' }]).ui).toBe('listening')
  })
  it('VAD events outside their states are ignored (same object)', () => {
    expect(reduce(initialState, { type: 'VAD_END' })).toBe(initialState)
    const rb = run([sc('READBACK_PLAYED', draft)])
    expect(reduce(rb, { type: 'VAD_START' })).toBe(rb)
  })
  it('stores partial and final transcripts', () => {
    const s = run([{ type: 'TRANSCRIPT_PARTIAL', text: 'send' }])
    expect(s.partial).toBe('send')
    const f = reduce(s, { type: 'TRANSCRIPT_FINAL', text: 'send 5000' })
    expect(f.transcript).toBe('send 5000')
    expect(f.partial).toBe('')
  })
})

describe('machine: transfer flow', () => {
  it('READBACK_PLAYED enters readback with the draft; repeat loops', () => {
    const s = run([{ type: 'VAD_START' }, { type: 'VAD_END' }, sc('DRAFTED', draft), sc('READBACK_PLAYED', draft)])
    expect(s.ui).toBe('readback')
    expect(s.draft).toEqual(draft)
    expect(reduce(s, sc('READBACK_PLAYED')).ui).toBe('readback')
    expect(reduce(s, sc('READBACK_PLAYED')).draft).toEqual(draft)
  })
  it('server listening keeps readback', () => {
    const s = run([sc('READBACK_PLAYED', draft)])
    expect(reduce(s, { type: 'SERVER_LISTENING' })).toBe(s)
  })
  it('CONFIRMED_BY_VOICE and AWAITING_BIOMETRIC do not change the panel', () => {
    const s = run([sc('READBACK_PLAYED', draft), sc('CONFIRMED_BY_VOICE'), sc('AWAITING_BIOMETRIC')])
    expect(s.ui).toBe('readback')
  })
  it('approval.request enters fingerprint', () => {
    const s = run([sc('READBACK_PLAYED', draft), { type: 'APPROVAL_REQUEST', transferId: 't1' }])
    expect(s.ui).toBe('fingerprint')
  })
  it('APPROVED and SUBMITTED enter sending', () => {
    const s = run([sc('READBACK_PLAYED', draft), { type: 'APPROVAL_REQUEST', transferId: 't1' }, sc('APPROVED')])
    expect(s.ui).toBe('sending')
    expect(reduce(s, sc('SUBMITTED')).ui).toBe('sending')
  })
  it('SETTLED / FAILED / PENDING_UNKNOWN enter result', () => {
    const sending = run([sc('READBACK_PLAYED', draft), sc('SUBMITTED')])
    expect(reduce(sending, sc('SETTLED', { ...draft, reference: 'X1' })).result).toBe('settled')
    expect(reduce(sending, sc('FAILED', { ...draft, failureReason: 'No' })).result).toBe('failed')
    expect(reduce(sending, sc('PENDING_UNKNOWN')).result).toBe('pending')
  })
  it('pending then settled resolves; settled is not downgraded to pending', () => {
    const pending = run([sc('SUBMITTED', draft), sc('PENDING_UNKNOWN')])
    expect(reduce(pending, sc('SETTLED')).result).toBe('settled')
    const settled = run([sc('SUBMITTED', draft), sc('SETTLED')])
    expect(reduce(settled, sc('PENDING_UNKNOWN'))).toBe(settled)
  })
  it('CANCELLED and EXPIRED enter cancelled', () => {
    expect(run([sc('READBACK_PLAYED', draft), sc('CANCELLED')]).cancel).toBe('cancelled')
    expect(run([sc('AWAITING_BIOMETRIC'), { type: 'APPROVAL_REQUEST', transferId: 't1' }, sc('EXPIRED')]).cancel).toBe('expired')
  })
  it('late READBACK_PLAYED does not pull a finished transfer back', () => {
    const done = run([sc('SETTLED', draft)])
    expect(reduce(done, sc('READBACK_PLAYED'))).toBe(done)
  })
  it('LOCAL_CANCEL only works from fingerprint', () => {
    const fp = run([sc('READBACK_PLAYED', draft), { type: 'APPROVAL_REQUEST', transferId: 't1' }])
    expect(reduce(fp, { type: 'LOCAL_CANCEL' }).ui).toBe('cancelled')
    expect(reduce(initialState, { type: 'LOCAL_CANCEL' })).toBe(initialState)
  })
})

describe('machine: return to listening', () => {
  it('returns after result and cancel, clearing the draft', () => {
    const settled = run([sc('SETTLED', draft)])
    const back = reduce(settled, { type: 'RETURN_TO_LISTENING' })
    expect(back.ui).toBe('listening')
    expect(back.draft).toBeNull()
    expect(back.transcript).toBe('')
    expect(reduce(run([sc('CANCELLED')]), { type: 'RETURN_TO_LISTENING' }).ui).toBe('listening')
  })
  it('never returns while pending', () => {
    const pending = run([sc('PENDING_UNKNOWN', draft)])
    expect(reduce(pending, { type: 'RETURN_TO_LISTENING' })).toBe(pending)
  })
  it('does not return from other states', () => {
    const rb = run([sc('READBACK_PLAYED', draft)])
    expect(reduce(rb, { type: 'RETURN_TO_LISTENING' })).toBe(rb)
  })
})

describe('machine: errors', () => {
  it('server error opens the overlay without changing the panel', () => {
    const rb = run([sc('READBACK_PLAYED', draft)])
    const e = reduce(rb, { type: 'SERVER_ERROR', code: 'provider_down', promptId: 'err_provider_down' })
    expect(e.ui).toBe('readback')
    expect(e.error).toEqual({ code: 'provider_down', promptId: 'err_provider_down' })
    expect(reduce(e, { type: 'DISMISS_ERROR' }).error).toBeNull()
  })
  it('unclear errors are soft (no overlay)', () => {
    const s = reduce(initialState, { type: 'SERVER_ERROR', code: 'unclear_reply', promptId: 'say_yes_no_repeat' })
    expect(s.error).toBeNull()
    expect(s.unclear).toBe(true)
  })
  it('transport loss opens and restore closes the overlay', () => {
    const lost = reduce(initialState, { type: 'TRANSPORT_LOST' })
    expect(lost.error?.promptId).toBe('err_connection_lost')
    expect(reduce(lost, { type: 'TRANSPORT_RESTORED' }).error).toBeNull()
  })
  it('restore does not clear other errors', () => {
    const mic = reduce(initialState, { type: 'MIC_DENIED' })
    expect(reduce(mic, { type: 'TRANSPORT_RESTORED' })).toBe(mic)
  })
  it('the overlay survives return to listening', () => {
    const s = run([sc('CANCELLED'), { type: 'MIC_DENIED' }, { type: 'RETURN_TO_LISTENING' }])
    expect(s.error?.code).toBe('mic_denied')
  })
})
