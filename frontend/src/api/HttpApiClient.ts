import { z } from 'zod'
import {
  asCreationOptions, asUnlockChallenge, balanceWire, configWire, consentWire, healthWire, historyWire, lockOptionsWire, lockStatusWire,
  mapBalance, mapConfig, mapHistory, mapMe, mapReceipt, mapTransfer, meWire, receiptWire, registerOptionsWire, registerVerifyWire, transferWire,
} from './rest'
import { request } from './http'
import type { ApiClient } from './ApiClient'
import type { HistoryQuery } from './types'

const anything = z.unknown()
const sourceWire = z.looseObject({ source_account: z.string() })

/** Real backend over HTTP (REST surface of the Avenza backend, docs/PROTOCOL.md section 8). */
export class HttpApiClient implements ApiClient {
  async health() {
    const d = await request('/health', (x) => healthWire.parse(x), { auth: false, timeoutMs: 6000 })
    return { ok: d.status === 'ok', bankMode: d.bank.mode, bankSimulated: d.bank.simulated, bankReady: d.bank.ready ?? true }
  }
  config() {
    return request('/config', (x) => mapConfig(configWire.parse(x)), { auth: false })
  }
  async registerOptions(input: Parameters<ApiClient['registerOptions']>[0]) {
    const d = await request('/devices/register/options', (x) => registerOptionsWire.parse(x), {
      auth: false,
      body: {
        display_name: input.displayName.trim(),
        language: input.language,
        ...(input.existing ? { user_id: input.existing.userId, device_token: input.existing.deviceToken } : {}),
      },
    })
    return { challengeId: d.challenge_id, userId: d.user_id, options: asCreationOptions(d) }
  }
  async registerVerify(input: Parameters<ApiClient['registerVerify']>[0]) {
    const d = await request('/devices/register/verify', (x) => registerVerifyWire.parse(x), {
      auth: false,
      body: { challenge_id: input.challengeId, credential: input.credential },
    })
    return { deviceToken: d.device_token, userId: d.user_id }
  }
  async createConsent(input: Parameters<ApiClient['createConsent']>[0]) {
    const d = await request('/consents', (x) => consentWire.parse(x), {
      body: { wording_version: input.wordingVersion, language: input.language },
    })
    return { consentId: d.consent_id }
  }
  me() {
    return request('/me', (x) => mapMe(meWire.parse(x)))
  }
  async setSourceAccount(accountNumber: string) {
    const d = await request('/me/source-account', (x) => sourceWire.parse(x), { method: 'PUT', body: { account_number: accountNumber } })
    return { sourceAccount: d.source_account }
  }
  balance() {
    return request('/me/balance', (x) => mapBalance(balanceWire.parse(x)))
  }
  history(query: HistoryQuery = {}) {
    return request('/transfers', (x) => mapHistory(historyWire.parse(x)), {
      query: { start: query.start, end: query.end, limit: query.limit },
    })
  }
  transfer(transferId: string) {
    return request(`/transfers/${encodeURIComponent(transferId)}`, (x) => mapTransfer(transferWire.parse(x)))
  }
  receipt(transferId: string) {
    return request(`/transfers/${encodeURIComponent(transferId)}/receipt`, (x) => mapReceipt(receiptWire.parse(x)))
  }
  async lockStatus() {
    return (await request('/locks/status', (x) => lockStatusWire.parse(x))).locked
  }
  async lock() {
    await request('/locks', (x) => anything.parse(x), { method: 'POST', body: {} })
  }
  async unlockOptions() {
    return asUnlockChallenge(await request('/locks/options', (x) => lockOptionsWire.parse(x), { method: 'POST', body: {} }))
  }
  async unlockVerify(input: Parameters<ApiClient['unlockVerify']>[0]) {
    await request('/locks/unlock', (x) => anything.parse(x), { method: 'POST', body: { challenge_id: input.challengeId, credential: input.credential } })
  }
}
