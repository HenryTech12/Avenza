import type { ApiClient } from '../api/ApiClient'
import type { TransferDetail } from '../api/types'
import type { ServerMessage, TransferDraft } from '../protocol/messages'

const NEW_RECIPIENT_FLAGS = ['new_recipient_large', 'new_recipient']

function draftOf(d: TransferDetail, reference?: string): TransferDraft {
  return {
    amountKobo: d.amountKobo,
    recipientName: d.recipient,
    bankName: d.bankName ?? '',
    accountMasked: d.accountMasked || (d.accountLast4 ? `•••• ${d.accountLast4}` : ''),
    reference: reference ?? d.reference ?? undefined,
    failureReason: d.failureReason ?? undefined,
    isNewRecipient: d.riskFlags.some((f) => NEW_RECIPIENT_FLAGS.includes(f)),
  }
}

/**
 * The backend's `state.changed` carries only the amount text and recipient. The bank name and masked account
 * for the read-back screen come from `GET /transfers/{id}` (once per transfer; again on FAILED for the reason).
 */
export function createEnricher(api: Pick<ApiClient, 'transfer'>) {
  const cache = new Map<string, TransferDetail>()

  return async function enrich(msg: ServerMessage): Promise<ServerMessage> {
    if (msg.type !== 'state.changed') return msg
    let detail = cache.get(msg.transferId)
    if (!detail || msg.state === 'FAILED') {
      try {
        detail = await api.transfer(msg.transferId)
        cache.set(msg.transferId, detail)
      } catch {
        if (!detail) return msg // keep the amount and name the message itself carries
      }
    }
    return { ...msg, draft: draftOf(detail, msg.draft?.reference) }
  }
}
