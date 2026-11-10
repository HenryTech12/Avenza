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
