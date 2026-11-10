/**
 * Protocol types. Field names live in this file and schemas.ts only: if the backend
 * uses snake_case, adapt them there without touching screens.
 */
import type {
  AuthenticationResponseJSON,
  PublicKeyCredentialRequestOptionsJSON,
  PublicKeyCredentialCreationOptionsJSON,
  RegistrationResponseJSON,
} from '@simplewebauthn/browser'

export type {
  AuthenticationResponseJSON,
  PublicKeyCredentialRequestOptionsJSON,
  PublicKeyCredentialCreationOptionsJSON,
  RegistrationResponseJSON,
}

export type Lang = 'en' | 'yo' | 'ha' | 'ig'

export type TransferState =
  | 'DRAFTED'
  | 'READBACK_PLAYED'
  | 'CONFIRMED_BY_VOICE'
  | 'AWAITING_BIOMETRIC'
  | 'APPROVED'
  | 'SUBMITTED'
  | 'SETTLED'
  | 'FAILED'
  | 'PENDING_UNKNOWN'
  | 'CANCELLED'
  | 'EXPIRED'

export interface TransferDraft {
  amountKobo: number // integer kobo, display only
  recipientName: string // bank-verified name
  bankName: string
  accountMasked: string
  reference?: string
  failureReason?: string
  isNewRecipient?: boolean
}

export type ClientMessage =
  | { type: 'session.start'; deviceToken: string; consentId: string; language: Lang }
  | { type: 'utterance.start'; sampleRate: number }
  | { type: 'utterance.end' }
  | { type: 'approval.response'; transferId: string; assertion: AuthenticationResponseJSON }
  | { type: 'confirm.response'; transferId: string; answer: 'yes' | 'no' | 'repeat' } // needs backend agreement

export type ServerMessage =
  | { type: 'transcript.partial'; text: string }
  | { type: 'transcript.final'; text: string }
  | {
      type: 'prompt.play'
      promptId?: string // a prompt the app has cached itself (mock mode)
      clipUrl?: string // a URL to play, or `speak:<text>` (mock mode)
      /** Live backend: the server says what to speak, and may attach audio. */
      text?: string
      audioUrl?: string
      audio?: { sampleRate: number; pcm: Int16Array }
      warnings?: string[]
    }
  | { type: 'audio.stream'; sampleRate: number; final: boolean }
  | { type: 'approval.request'; transferId: string; options: PublicKeyCredentialRequestOptionsJSON; draft?: TransferDraft }
  | { type: 'state.changed'; transferId: string; state: TransferState; draft?: TransferDraft }
  | { type: 'listening' }
  | { type: 'error'; code: string; promptId: string; message?: string }
  | { type: 'session.ready'; language: string; languageVerified: boolean; bankSimulated: boolean; approvalTtlS: number | null }
  | { type: 'lock.changed'; locked: boolean }

export interface AudioChunk {
  pcm: Int16Array
  sampleRate: number
  final: boolean
}

