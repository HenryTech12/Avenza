export type ToneName = 'tone_listening' | 'tone_confirmed' | 'tone_success' | 'tone_error'

interface Note {
  freq: number
  start: number // seconds
  dur: number
  gain?: number
}

const SCORES: Record<ToneName, Note[]> = {
  // soft rising two-note: "I'm listening now"
  tone_listening: [
    { freq: 660, start: 0, dur: 0.09 },
    { freq: 880, start: 0.09, dur: 0.12 },
  ],
  tone_confirmed: [{ freq: 740, start: 0, dur: 0.14 }],
  // bright arpeggio
  tone_success: [
    { freq: 523.25, start: 0, dur: 0.11 },
    { freq: 659.25, start: 0.1, dur: 0.11 },
    { freq: 783.99, start: 0.2, dur: 0.22 },
  ],
  // low falling
  tone_error: [
    { freq: 330, start: 0, dur: 0.16 },
    { freq: 247, start: 0.16, dur: 0.26 },
  ],
}

export const toneNames = Object.keys(SCORES) as ToneName[]

/** Render a tone to mono samples (pure; used by the cache and by tests). */
export function renderTone(name: ToneName, sampleRate: number): Float32Array {
  const score = SCORES[name]
  const total = Math.max(...score.map((n) => n.start + n.dur)) + 0.05
  const out = new Float32Array(Math.ceil(total * sampleRate))
  for (const n of score) {
    const from = Math.floor(n.start * sampleRate)
    const len = Math.floor(n.dur * sampleRate)
    const peak = n.gain ?? 0.28
    for (let i = 0; i < len && from + i < out.length; i++) {
      const t = i / sampleRate
      // 8 ms attack, exponential-ish release: no clicks
      const attack = Math.min(1, t / 0.008)
      const release = Math.min(1, (len - i) / (0.03 * sampleRate))
      out[from + i] += Math.sin(2 * Math.PI * n.freq * t) * peak * attack * release
    }
  }
  return out
}

const cache = new Map<string, AudioBuffer>()

export function getToneBuffer(ctx: AudioContext, name: ToneName): AudioBuffer {
  const key = `${name}@${ctx.sampleRate}`
  let b = cache.get(key)
  if (!b) {
    const data = renderTone(name, ctx.sampleRate)
    b = ctx.createBuffer(1, data.length, ctx.sampleRate)
    b.copyToChannel(data as Float32Array<ArrayBuffer>, 0)
    cache.set(key, b)
  }
  return b
}
