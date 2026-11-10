import type { TransferState } from './messages'

/** Terminal server states: the transfer is over. */
export const terminalStates: readonly TransferState[] = ['SETTLED', 'FAILED', 'CANCELLED', 'EXPIRED']

export function isTerminal(s: TransferState): boolean {
  return terminalStates.includes(s)
}
