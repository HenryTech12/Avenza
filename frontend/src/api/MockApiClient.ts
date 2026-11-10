import type { PublicKeyCredentialCreationOptionsJSON } from '../protocol/messages'
import type { ApiClient } from './ApiClient'
import type { HistoryItem, Receipt } from './types'

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms))

function b64url(s: string): string {
  return btoa(s).replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_')
}

const daysAgo = (d: number, h = 9, m = 14) => {
  const t = new Date()
  t.setDate(t.getDate() - d)
  t.setHours(h, m, 0, 0)
  return t.toISOString()
}

const mockHistory: HistoryItem[] = [
  { id: 'tr_m1', state: 'SETTLED', display: 'Settled', amountKobo: 500000, amountDisplay: '₦5,000.00', bankName: 'GTBank', accountLast4: '4821', recipient: 'Aisha Bello', reference: 'AVZ482910337', createdAt: daysAgo(0), settledAt: daysAgo(0), failureReason: null, riskFlags: [] },
  { id: 'tr_m2', state: 'FAILED', display: 'Failed', amountKobo: 1250000, amountDisplay: '₦12,500.00', bankName: 'Access Bank', accountLast4: '7305', recipient: 'Chukwuemeka Obi', reference: null, createdAt: daysAgo(1, 17, 40), settledAt: null, failureReason: 'insufficient_funds', riskFlags: [] },
  { id: 'tr_m3', state: 'SETTLED', display: 'Settled', amountKobo: 200000, amountDisplay: '₦2,000.00', bankName: 'First Bank', accountLast4: '2290', recipient: 'Musa Ibrahim', reference: 'AVZ482114552', createdAt: daysAgo(6, 12, 5), settledAt: daysAgo(6, 12, 5), failureReason: null, riskFlags: [] },
  { id: 'tr_m4', state: 'CANCELLED', display: 'Cancelled', amountKobo: 7500000, amountDisplay: '₦75,000.00', bankName: 'GTBank', accountLast4: '4821', recipient: 'Aisha Bello', reference: null, createdAt: daysAgo(8, 8, 30), settledAt: null, failureReason: null, riskFlags: ['new_recipient_large'] },
]

/** Built-in data for mock mode. The live client is HttpApiClient. */
export class MockApiClient implements ApiClient {
  private locked = false
  private source: string | null = '0123456789'

  async health() {
    await wait(100)
    return { ok: true, bankMode: 'mock', bankSimulated: true, bankReady: true }
  }
  async config() {
    await wait(100)
    return {
      bank: { mode: 'mock', simulated: true },
      limits: { maxAmountDisplay: '₦1,000,000.00', largeAmountDisplay: '₦50,000.00', newRecipientHoldS: 10 },
      allowTextUtterance: true,
      verifiedLanguages: ['en'],
      demoAccounts: [],
      sourceAccounts: [
        { accountNumber: '0123456789', accountName: 'Adaeze Chiamaka Okonkwo', tier: '3' },
        { accountNumber: '0123456790', accountName: 'Babatunde Olumide Adeyemi', tier: '3' },
      ],
    }
  }
  async registerOptions(): ReturnType<ApiClient['registerOptions']> {
    await wait(150)
    const options: PublicKeyCredentialCreationOptionsJSON = {
      challenge: b64url(`mock-register-${Date.now()}`),
      rp: { name: 'Avenza', id: location.hostname },
      user: { id: b64url('mock-user-1'), name: 'avenza-customer', displayName: 'Avenza customer' },
      pubKeyCredParams: [
        { type: 'public-key', alg: -7 },
        { type: 'public-key', alg: -257 },
      ],
      timeout: 60000,
      attestation: 'none',
      authenticatorSelection: {
        authenticatorAttachment: 'platform',
        userVerification: 'required',
        residentKey: 'required',
        requireResidentKey: true,
      },
    }
    return { challengeId: 'wac_mock', userId: 'mock-user-1', options }
  }
  async registerVerify() {
    await wait(200)
    return { deviceToken: `dev_${Math.random().toString(36).slice(2, 10)}`, userId: 'mock-user-1' }
  }
  async createConsent() {
    await wait(150)
    return { consentId: `con_${Math.random().toString(36).slice(2, 10)}` }
  }
  async me() {
    await wait(80)
    return { id: 'mock-user-1', displayName: 'Demo customer', language: 'en', sourceAccount: this.source }
  }
  async setSourceAccount(accountNumber: string) {
    await wait(120)
    this.source = accountNumber
    return { sourceAccount: accountNumber }
  }
  async balance() {
    await wait(120)
    return { availableKobo: 18_425_000, availableDisplay: '₦184,250.00', currency: 'NGN' }
  }
  async history(query: { start?: string; end?: string; limit?: number } = {}) {
    await wait(150)
    const start = query.start ? Date.parse(query.start) : 0
    const end = query.end ? Date.parse(query.end) : Date.now() + 1000
    const items = mockHistory.filter((i) => {
      const at = Date.parse(i.createdAt ?? '')
      return at >= start && at <= end
    })
    return { items: items.slice(0, query.limit ?? 50), simulated: true }
  }
  async transfer(transferId: string) {
    const item = mockHistory.find((i) => i.id === transferId)
    if (!item) throw new Error('not found')
    return { ...item, accountMasked: `•••• ${item.accountLast4}` }
  }
  async receipt(transferId: string): Promise<Receipt> {
    await wait(120)
    const item = mockHistory.find((i) => i.id === transferId)
    if (!item?.reference) throw new Error('not submitted')
    return {
      reference: item.reference,
      amountKobo: item.amountKobo,
      recipientName: item.recipient,
      status: item.state,
      fee: 10_00,
      vat: 0,
      stampDuty: 0,
      totalDebit: item.amountKobo + 10_00,
      createdAt: item.createdAt,
      bank: 'Simulated bank',
      simulated: true,
    }
  }
  async lockStatus() {
    return this.locked
  }
  async lock() {
    this.locked = true
  }
  async unlockOptions() {
    return {
      challengeId: 'wac_mock_unlock',
      options: {
        challenge: b64url(`unlock-${Date.now()}`),
        rpId: location.hostname,
        userVerification: 'required' as const,
        timeout: 60000,
        allowCredentials: [],
      },
    }
  }
  async unlockVerify() {
    this.locked = false
  }
}
