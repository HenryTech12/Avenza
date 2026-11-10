import { signal } from '@preact/signals'

export interface LogEntry {
  dir: 'in' | 'out'
  type: string
  at: number
}

/** Last 50 protocol messages (type only, never content), for the dev panel. */
export const protocolLog = signal<LogEntry[]>([])

export function logMessage(dir: 'in' | 'out', type: string): void {
  // peek(): send() is called from effects (reconnect -> session.start). Reading .value there subscribed
  // the effect to this log, so writing it threw "Cycle detected" before the message went out.
  const next = [...protocolLog.peek(), { dir, type, at: Date.now() }]
  protocolLog.value = next.length > 50 ? next.slice(next.length - 50) : next
}
