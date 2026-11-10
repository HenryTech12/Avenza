import type {
  AuthenticationResponseJSON,
  Lang,
  PublicKeyCredentialCreationOptionsJSON,
  RegistrationResponseJSON,
} from '../protocol/messages'
import type { BackendConfig, Balance, History, HistoryQuery, Me, Receipt, TransferDetail, UnlockChallenge } from './types'

export interface HealthInfo {
  ok: boolean
  bankMode: string
  bankSimulated: boolean
  bankReady: boolean
}

export interface RegistrationStart {
  challengeId: string
  userId: string
  options: PublicKeyCredentialCreationOptionsJSON
}

/** Everything the app asks of the backend over HTTP. Mock and live implementations are interchangeable. */
export interface ApiClient {
  health(): Promise<HealthInfo>
  config(): Promise<BackendConfig>
  registerOptions(input: { displayName: string; language: Lang; existing?: { userId: string; deviceToken: string } }): Promise<RegistrationStart>
  registerVerify(input: { challengeId: string; credential: RegistrationResponseJSON }): Promise<{ deviceToken: string; userId: string }>
  createConsent(input: { wordingVersion: string; language: Lang }): Promise<{ consentId: string }>
  me(): Promise<Me>
  setSourceAccount(accountNumber: string): Promise<{ sourceAccount: string }>
  balance(): Promise<Balance>
  history(query?: HistoryQuery): Promise<History>
  transfer(transferId: string): Promise<TransferDetail>
  receipt(transferId: string): Promise<Receipt>
  lockStatus(): Promise<boolean>
  lock(): Promise<void>
  unlockOptions(): Promise<UnlockChallenge>
  unlockVerify(input: { challengeId: string; credential: AuthenticationResponseJSON }): Promise<void>
}
