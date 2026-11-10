import { signal } from '@preact/signals'

export interface LogEntry {
  dir: 'in' | 'out'
  type: string
  at: number
}

/** Last 50 protocol messages (type only, never content), for the dev panel. */
export const protocolLog = signal<LogEntry[]>([])

export function logMessage(dir: 'in' | 'out', type: string): void {
  const next = [...protocolLog.value, { dir, type, at: Date.now() }]
  protocolLog.value = next.length > 50 ? next.slice(next.length - 50) : next
}
