/** Domain types returned by the REST API. Backend field names (snake_case) are mapped in `mappers.ts` only. */
export interface DemoAccount {
  bankCode: string
  bankName: string
  accountNumber: string
  accountName: string
}

export interface SourceAccount {
  accountNumber: string
  accountName: string
  tier: string
}

export interface BackendConfig {
  bank: { mode: string; simulated: boolean }
  limits: { maxAmountDisplay: string; largeAmountDisplay: string; newRecipientHoldS: number }
  allowTextUtterance: boolean
  verifiedLanguages: string[]
  demoAccounts: DemoAccount[]
  sourceAccounts: SourceAccount[]
}

export interface Me {
  id: string
  displayName: string
  language: string
  sourceAccount: string | null
}

export interface Balance {
  availableKobo: number | null
  availableDisplay: string | null
  currency: string
}

export type HistoryState = string

export interface HistoryItem {
  id: string | null
  state: HistoryState
  display: string
  amountKobo: number
  amountDisplay: string
  bankName: string | null
  accountLast4: string
  recipient: string
  reference: string | null
  createdAt: string | null
  settledAt: string | null
  failureReason: string | null
  riskFlags: string[]
}

export interface TransferDetail extends HistoryItem {
  accountMasked: string
}

export interface HistoryQuery {
  start?: string // ISO-8601
  end?: string
  limit?: number // 1..100
}

export interface History {
  items: HistoryItem[]
  simulated: boolean
}

export interface Receipt {
  reference: string
  amountKobo: number | null
  recipientName: string | null
  status: string | null
  fee: number | string | null
  vat: number | string | null
  stampDuty: number | string | null
  totalDebit: number | string | null
  createdAt: string | null
  bank: string | null
  simulated: boolean
}

export interface UnlockChallenge {
  challengeId: string
  options: import('../protocol/messages').PublicKeyCredentialRequestOptionsJSON
}
