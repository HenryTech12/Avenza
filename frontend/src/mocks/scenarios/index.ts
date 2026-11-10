import type { TransferDraft } from '../../protocol/messages'

export type Answer = 'yes' | 'no' | 'repeat' | 'unclear'

/**
 * A scenario is data. `scenarioRunner` interprets it, so every scenario shares one flow.
 *
 * Mock rule for answers: after the read-back, the Nth answer comes from the on-screen
 * buttons (confirm.response) if pressed, otherwise from `answers[N]` when the customer
 * speaks (any utterance counts as the next scripted answer). When `answers` runs out
 * the last one repeats.
 */
export interface Scenario {
  id: string
  description: string
  transcript: string
  draft: TransferDraft
  answers: Answer[]
  /** error on utterance.end instead of a draft */
  providerDown?: boolean
  /** 'expire': never answer approval.request; server sends EXPIRED after expireAfterMs */
  fingerprint: 'approve' | 'expire'
  expireAfterMs?: number
  /** transport drops during AWAITING_BIOMETRIC and re-sends state after reconnect */
  dropDuringFingerprint?: boolean
  outcome: 'settled' | 'pending_then_settled' | 'failed'
  failureReason?: string
  /** every server message is delayed by a random time in this range */
  delayMs?: [number, number]
}

const aisha: TransferDraft = {
  amountKobo: 500000,
  recipientName: 'Aisha Bello',
  bankName: 'GTBank',
  accountMasked: '•••• 4821',
}

const base: Omit<Scenario, 'id' | 'description'> = {
  transcript: 'Send five thousand naira to Aisha Bello',
  draft: aisha,
  answers: ['yes'],
  fingerprint: 'approve',
  outcome: 'settled',
}

const list: Scenario[] = [
  { ...base, id: 'happy_path', description: 'Speech, read-back, yes, fingerprint, settled.' },
  { ...base, id: 'say_no', description: 'Read-back, then no: cancelled.', answers: ['no'] },
  { ...base, id: 'repeat_then_yes', description: 'Read-back played twice, then approved.', answers: ['repeat', 'yes'] },
  { ...base, id: 'unclear_twice', description: 'Two unclear replies: cancelled.', answers: ['unclear', 'unclear'] },
  {
    ...base,
    id: 'fingerprint_fail',
    description: 'Fingerprint rejected, retry, then cancelled. Reject or dismiss the prompt twice.',
  },
  {
    ...base,
    id: 'fingerprint_timeout',
    description: 'No fingerprint: the server expires the transfer.',
    fingerprint: 'expire',
    expireAfterMs: 15000,
  },
  { ...base, id: 'bank_timeout', description: 'Submitted, pending unknown for 4 s, then settled.', outcome: 'pending_then_settled' },
  {
    ...base,
    id: 'bank_failed',
    description: 'Submitted, then failed: recipient bank unavailable.',
    draft: { ...aisha, amountKobo: 1250000, recipientName: 'Chukwuemeka Obi', bankName: 'Access Bank', accountMasked: '•••• 7305' },
    transcript: 'Send twelve thousand five hundred naira to Chukwuemeka Obi',
    outcome: 'failed',
    failureReason: 'Recipient bank unavailable',
  },
  { ...base, id: 'provider_down', description: 'Speech provider error on the first utterance.', providerDown: true },
  { ...base, id: 'ws_drop', description: 'Connection drops during the fingerprint step and returns after 3 s.', dropDuringFingerprint: true },
  { ...base, id: 'slow_network', description: 'Every message is delayed 1.5 to 3 s.', delayMs: [1500, 3000] },
  {
    ...base,
    id: 'new_recipient_large',
    description: 'New recipient, large amount (scam pause flag).',
    transcript: 'Send two hundred and fifty thousand naira to Musa Ibrahim',
    draft: {
      amountKobo: 25000000,
      recipientName: 'Musa Ibrahim',
      bankName: 'First Bank',
      accountMasked: '•••• 2290',
      isNewRecipient: true,
    },
  },
]

export const scenarios: Record<string, Scenario> = Object.fromEntries(list.map((s) => [s.id, s]))
export const scenarioIds = list.map((s) => s.id)

export function getScenario(id: string): Scenario {
  return scenarios[id] ?? scenarios.happy_path
}
