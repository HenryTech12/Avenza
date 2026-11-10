import { api } from '../api'
import { ApiError } from '../api/http'
import type { HistoryQuery } from '../api/types'
import { t } from '../i18n'

export type { BackendConfig, Balance, History, HistoryItem, Me, Receipt, SourceAccount } from '../api/types'

/** Account data screens: profile, balance, source account, history and receipts (the live or mock API). */
export const fetchProfile = () => api.me()
export const fetchBalance = () => api.balance()
export const fetchConfig = () => api.config()
export const chooseSourceAccount = (accountNumber: string) => api.setSourceAccount(accountNumber)
export const fetchHistory = (query?: HistoryQuery) => api.history(query)
export const fetchReceipt = (transferId: string) => api.receipt(transferId)

/** A message for the customer: the backend's own words when it sent some, otherwise a plain one. */
export function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.kind === 'network') return t('error.network')
    if (e.kind === 'timeout') return t('error.slow')
    if (e.kind === 'server' && !e.message) return t('error.server')
    return e.message
  }
  return t('error.generic')
}
