import { signal } from '@preact/signals'

let ctx: AudioContext | null = null

/** True once the shared context is running (user gesture has happened). */
export const audioRunning = signal(false)

/** The one shared AudioContext for the whole app. Never create a second one. */
export function getAudioContext(): AudioContext {
  if (!ctx) {
    const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
    ctx = new Ctor({ latencyHint: 'interactive' })
    ctx.onstatechange = () => {
      audioRunning.value = ctx?.state === 'running'
    }
    audioRunning.value = ctx.state === 'running'
  }
  return ctx
}

/**
 * True when the browser will let sound start without a touch: the customer already touched this page,
 * or Avenza runs as an installed app. Checking first avoids creating an AudioContext that the browser
 * refuses ("The AudioContext was not allowed to start" in the console).
 */
export function soundAllowedWithoutTouch(): boolean {
  if (ctx?.state === 'running') return true
  const activated = (navigator as Navigator & { userActivation?: { hasBeenActive: boolean } }).userActivation?.hasBeenActive
  const installed = window.matchMedia?.('(display-mode: standalone)').matches || (navigator as Navigator & { standalone?: boolean }).standalone === true
  // Automated test browsers are launched with autoplay allowed.
  return !!activated || !!installed || navigator.webdriver === true
}

let decoder: BaseAudioContext | null = null
/**
 * A context for decoding prompt clips before any touch. Decoding never plays sound, so an
 * OfflineAudioContext is enough and the browser does not complain; the AudioBuffers it makes
 * play on the real context later.
 */
export function getDecodeContext(): BaseAudioContext {
  if (ctx) return ctx
  if (!decoder) {
    const Offline = window.OfflineAudioContext ?? (window as unknown as { webkitOfflineAudioContext?: typeof OfflineAudioContext }).webkitOfflineAudioContext
    decoder = Offline ? new Offline(1, 1, 48000) : getAudioContext()
  }
  return decoder
}

/** Call from a user gesture (consent "I agree" or "Tap to start"). */
export async function resumeAudio(): Promise<boolean> {
  const c = getAudioContext()
  if (c.state !== 'running') {
    try {
      await c.resume()
    } catch {
      /* needs a gesture */
    }
  }
  audioRunning.value = c.state === 'running'
  return audioRunning.value
}
