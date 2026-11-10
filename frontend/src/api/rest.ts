import { z } from 'zod'
import type { PublicKeyCredentialCreationOptionsJSON, PublicKeyCredentialRequestOptionsJSON } from '../protocol/messages'
import type { Balance, BackendConfig, History, HistoryItem, Me, Receipt, TransferDetail, UnlockChallenge } from './types'

/** Wire schemas (backend snake_case) and their mapping to domain types. Nothing else knows these field names. */

const str = z.string()
const nullableStr = z.string().nullable().optional()
const money = z.union([z.number(), z.string()]).nullable().optional()

export const healthWire = z.looseObject({
  status: str,
  bank: z.looseObject({ mode: str, simulated: z.boolean(), ready: z.boolean().optional() }),
})

const demoWire = z.object({ bank_code: str, bank_name: str, account_number: str, account_name: str })
const sourceWire = z.object({ account_number: str, account_name: str, tier: z.union([str, z.number()]).transform(String) })

export const configWire = z.looseObject({
  bank: z.looseObject({ mode: str, simulated: z.boolean() }),
  allow_text_utterance: z.boolean().optional(),
  limits: z.looseObject({
    max_amount_display: str,
    large_amount_display: str,
    new_recipient_hold_s: z.number(),
  }),
  languages: z.looseObject({ verified: z.array(str) }),
  demo_accounts: z.array(demoWire).default([]),
  source_accounts: z.array(sourceWire).default([]),
})

export function mapConfig(d: z.infer<typeof configWire>): BackendConfig {
  return {
    bank: d.bank,
    limits: {
      maxAmountDisplay: d.limits.max_amount_display,
      largeAmountDisplay: d.limits.large_amount_display,
      newRecipientHoldS: d.limits.new_recipient_hold_s,
    },
    allowTextUtterance: d.allow_text_utterance ?? false,
    verifiedLanguages: d.languages.verified,
    demoAccounts: d.demo_accounts.map((a) => ({
      bankCode: a.bank_code,
      bankName: a.bank_name,
      accountNumber: a.account_number,
      accountName: a.account_name,
    })),
    sourceAccounts: d.source_accounts.map((a) => ({ accountNumber: a.account_number, accountName: a.account_name, tier: a.tier })),
  }
}

export const registerOptionsWire = z.looseObject({
  user_id: str,
  challenge_id: str,
  publicKey: z.looseObject({ challenge: str }),
})
export const registerVerifyWire = z.looseObject({ user_id: str, device_id: str, device_token: str, display_name: str.optional() })
export const consentWire = z.looseObject({ consent_id: str })

export const meWire = z.looseObject({
  user: z.looseObject({ id: str, display_name: str, language: str, source_account: nullableStr }),
})
export const mapMe = (d: z.infer<typeof meWire>): Me => ({
  id: d.user.id,
  displayName: d.user.display_name,
  language: d.user.language,
  sourceAccount: d.user.source_account ?? null,
})

export const balanceWire = z.looseObject({
  available_kobo: z.number().nullable().optional(),
  available_display: nullableStr,
  currency: str.optional(),
})
export const mapBalance = (d: z.infer<typeof balanceWire>): Balance => ({
  availableKobo: d.available_kobo ?? null,
  availableDisplay: d.available_display ?? null,
  currency: d.currency ?? 'NGN',
})

export const summaryWire = z.looseObject({
  id: z.string().nullable().optional(),
  state: str,
  display: str.optional(),
  amount_kobo: z.number(),
  amount_display: str.optional(),
  bank_name: nullableStr,
  account_last4: str.optional(),
  recipient: nullableStr,
  reference: nullableStr,
  risk_flags: z.array(str).optional(),
  created_at: nullableStr,
  settled_at: nullableStr,
  failure_reason: nullableStr,
})
export type SummaryWire = z.infer<typeof summaryWire>

export function mapSummary(d: SummaryWire): HistoryItem {
  return {
    id: d.id ?? null,
    state: d.state,
    display: d.display ?? d.state,
    amountKobo: d.amount_kobo,
    amountDisplay: d.amount_display ?? '',
    bankName: d.bank_name ?? null,
    accountLast4: d.account_last4 ?? '',
    recipient: d.recipient ?? '',
    reference: d.reference ?? null,
    createdAt: d.created_at ?? null,
    settledAt: d.settled_at ?? null,
    failureReason: d.failure_reason ?? null,
    riskFlags: d.risk_flags ?? [],
  }
}

export const transferWire = summaryWire.extend({ account_number_masked: z.string().optional() })
export const mapTransfer = (d: z.infer<typeof transferWire>): TransferDetail => ({
  ...mapSummary(d),
  accountMasked: d.account_number_masked ? `•••• ${d.account_number_masked.slice(-4)}` : '',
})

export const historyWire = z.looseObject({ transactions: z.array(summaryWire), bank_simulated: z.boolean().optional() })
export const mapHistory = (d: z.infer<typeof historyWire>): History => ({
  items: d.transactions.map(mapSummary),
  simulated: d.bank_simulated ?? false,
})

export const receiptWire = z.looseObject({
  reference: str,
  amount_kobo: z.number().nullable().optional(),
  recipient_name: nullableStr,
  status: nullableStr,
  fee: money,
  vat: money,
  stamp_duty: money,
  total_debit: money,
  created_at: nullableStr,
  bank: nullableStr,
  simulated: z.boolean().optional(),
})
export const mapReceipt = (d: z.infer<typeof receiptWire>): Receipt => ({
  reference: d.reference,
  amountKobo: d.amount_kobo ?? null,
  recipientName: d.recipient_name ?? null,
  status: d.status ?? null,
  fee: d.fee ?? null,
  vat: d.vat ?? null,
  stampDuty: d.stamp_duty ?? null,
  totalDebit: d.total_debit ?? null,
  createdAt: d.created_at ?? null,
  bank: d.bank ?? null,
  simulated: d.simulated ?? false,
})

export const lockStatusWire = z.looseObject({ locked: z.boolean() })
export const lockOptionsWire = z.looseObject({ challenge_id: str, publicKey: z.looseObject({ challenge: str }) })

export const asCreationOptions = (d: z.infer<typeof registerOptionsWire>) => d.publicKey as unknown as PublicKeyCredentialCreationOptionsJSON
export const asUnlockChallenge = (d: z.infer<typeof lockOptionsWire>): UnlockChallenge => ({
  challengeId: d.challenge_id,
  options: d.publicKey as unknown as PublicKeyCredentialRequestOptionsJSON,
})
