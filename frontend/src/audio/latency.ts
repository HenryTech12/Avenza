import { signal } from '@preact/signals'

export interface LatencyTurn {
  endToFirstSoundMs: number | null
  endToReadbackMs: number | null
}

/** Dev-panel latency overlay data. Timestamps only; no content is stored. */
export const lastTurn = signal<LatencyTurn>({ endToFirstSoundMs: null, endToReadbackMs: null })

let speechEnd = 0
let gotFirstSound = false
let gotReadback = false

export function markSpeechEnd(): void {
  speechEnd = performance.now()
  gotFirstSound = false
  gotReadback = false
  lastTurn.value = { endToFirstSoundMs: null, endToReadbackMs: null }
}

export function markServerMessage(type: string): void {
  if (!speechEnd) return
  if (type === 'state.changed' && !gotReadback) {
    // first state.changed after speech end approximates read-back readiness
    gotReadback = true
    lastTurn.value = { ...lastTurn.value, endToReadbackMs: Math.round(performance.now() - speechEnd) }
    log('read-back state', lastTurn.value.endToReadbackMs)
  }
}

export function markSoundStarted(): void {
  if (!speechEnd || gotFirstSound) return
  gotFirstSound = true
  lastTurn.value = { ...lastTurn.value, endToFirstSoundMs: Math.round(performance.now() - speechEnd) }
  log('first sound', lastTurn.value.endToFirstSoundMs)
}

function log(what: string, ms: number | null): void {
  if (import.meta.env.DEV) console.debug(`[avenza] latency ${what}: ${ms} ms`)
}
