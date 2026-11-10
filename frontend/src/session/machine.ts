import type { TransferDraft, TransferState } from '../protocol/messages'

export type UiState =
  | 'listening'
  | 'hearing'
  | 'checking'
  | 'readback'
  | 'fingerprint'
  | 'sending'
  | 'result'
  | 'cancelled'

export type ResultKind = 'settled' | 'failed' | 'pending'
export type CancelKind = 'cancelled' | 'expired'

export interface ErrorOverlay {
  code: string
  promptId: string
}

export interface MachineState {
  ui: UiState
  transferId: string | null
  draft: TransferDraft | null
  serverState: TransferState | null
  result: ResultKind | null
  cancel: CancelKind | null
  error: ErrorOverlay | null
  /** soft note after an unclear reply ("I didn't catch that") */
  unclear: boolean
  partial: string
  transcript: string
}

export type MachineEvent =
  | { type: 'SERVER_LISTENING' }
  | { type: 'VAD_START' }
  | { type: 'VAD_END' }
  | { type: 'TRANSCRIPT_PARTIAL'; text: string }
  | { type: 'TRANSCRIPT_FINAL'; text: string }
  | { type: 'STATE_CHANGED'; transferId: string; state: TransferState; draft?: TransferDraft }
  | { type: 'APPROVAL_REQUEST'; transferId: string }
  | { type: 'SERVER_ERROR'; code: string; promptId: string }
  | { type: 'DISMISS_ERROR' }
  | { type: 'TRANSPORT_LOST' }
  | { type: 'TRANSPORT_RESTORED' }
  | { type: 'MIC_DENIED' }
  | { type: 'LOCAL_CANCEL'; kind?: CancelKind } // fingerprint failed or timed out on the device
  | { type: 'RETURN_TO_LISTENING' }

export const initialState: MachineState = {
  ui: 'listening',
  transferId: null,
  draft: null,
  serverState: null,
  result: null,
  cancel: null,
  error: null,
  unclear: false,
  partial: '',
  transcript: '',
}

const fresh = (s: MachineState): MachineState => ({
  ...initialState,
  error: s.error,
})

/**
 * Pure reducer. Returns the *same object* when an event is ignored, so callers can
 * detect "ignored" with `next === prev` and log it. Nothing here guesses an outcome:
 * money-related states only come from `STATE_CHANGED`.
 */
export function reduce(s: MachineState, e: MachineEvent): MachineState {
  switch (e.type) {
    case 'SERVER_LISTENING':
      if (s.ui === 'checking' || s.ui === 'hearing') return { ...s, ui: 'listening', partial: '' }
      return s // readback keeps its card; others wait for their own events

    case 'VAD_START':
      if (s.ui === 'listening') return { ...s, ui: 'hearing', partial: '', unclear: false }
      return s

    case 'VAD_END':
      if (s.ui === 'hearing') return { ...s, ui: 'checking' }
      return s

    case 'TRANSCRIPT_PARTIAL':
      return { ...s, partial: e.text }

    case 'TRANSCRIPT_FINAL':
      return { ...s, transcript: e.text, partial: '' }

    case 'APPROVAL_REQUEST':
      if (s.ui === 'readback' || s.ui === 'checking' || s.ui === 'fingerprint' || s.ui === 'hearing' || s.ui === 'listening') {
        return { ...s, ui: 'fingerprint', transferId: e.transferId, serverState: 'AWAITING_BIOMETRIC' }
      }
      return s

    case 'STATE_CHANGED': {
      const base = { ...s, transferId: e.transferId, serverState: e.state, draft: e.draft ?? s.draft }
      switch (e.state) {
        case 'DRAFTED':
          return base
        case 'READBACK_PLAYED':
          if (s.ui === 'result' || s.ui === 'cancelled' || s.ui === 'sending') return s
          return { ...base, ui: 'readback', unclear: false }
        case 'CONFIRMED_BY_VOICE':
        case 'AWAITING_BIOMETRIC':
          return base
        case 'APPROVED':
        case 'SUBMITTED':
          if (s.ui === 'result' || s.ui === 'cancelled') return s
          return { ...base, ui: 'sending' }
        case 'SETTLED':
          return { ...base, ui: 'result', result: 'settled', cancel: null }
        case 'FAILED':
          return { ...base, ui: 'result', result: 'failed', cancel: null }
        case 'PENDING_UNKNOWN':
          if (s.ui === 'result' && s.result === 'settled') return s
          return { ...base, ui: 'result', result: 'pending', cancel: null }
        case 'CANCELLED':
          return { ...base, ui: 'cancelled', cancel: 'cancelled', result: null }
        case 'EXPIRED':
          return { ...base, ui: 'cancelled', cancel: 'expired', result: null }
      }
      return s
    }

    case 'LOCAL_CANCEL':
      if (s.ui === 'fingerprint') return { ...s, ui: 'cancelled', cancel: e.kind ?? 'cancelled', result: null }
      return s

    case 'SERVER_ERROR':
      if (e.code.startsWith('unclear')) return { ...s, unclear: true }
      return { ...s, error: { code: e.code, promptId: e.promptId } }

    case 'DISMISS_ERROR':
      return s.error ? { ...s, error: null } : s

    case 'TRANSPORT_LOST':
      return { ...s, error: { code: 'connection_lost', promptId: 'err_connection_lost' } }

    case 'TRANSPORT_RESTORED':
      return s.error?.code === 'connection_lost' ? { ...s, error: null } : s

    case 'MIC_DENIED':
      return { ...s, error: { code: 'mic_denied', promptId: 'err_mic_denied' } }

    case 'RETURN_TO_LISTENING':
      if ((s.ui === 'result' && s.result !== 'pending') || s.ui === 'cancelled') return fresh(s)
      return s
  }
}
