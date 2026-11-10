/** Pure PCM helpers. No browser APIs, so they are unit-testable and usable inside the worklet. */

export const TARGET_RATE = 16000
export const FRAME_SAMPLES = 320 // 20 ms at 16 kHz
export const FRAME_BYTES = FRAME_SAMPLES * 2

export function floatToInt16(input: Float32Array): Int16Array {
  const out = new Int16Array(input.length)
  for (let i = 0; i < input.length; i++) {
    const s = Math.max(-1, Math.min(1, input[i]))
    out[i] = s < 0 ? Math.round(s * 0x8000) : Math.round(s * 0x7fff)
  }
  return out
}

export function int16ToFloat(input: Int16Array): Float32Array {
  const out = new Float32Array(input.length)
  for (let i = 0; i < input.length; i++) out[i] = input[i] / (input[i] < 0 ? 0x8000 : 0x7fff)
  return out
}

/** Stateless linear resample of a whole buffer (used for playback chunks). */
export function resampleLinear(input: Float32Array, fromRate: number, toRate: number): Float32Array {
  if (fromRate === toRate || input.length === 0) return input
  const ratio = fromRate / toRate
  const outLength = Math.max(1, Math.round(input.length / ratio))
  const out = new Float32Array(outLength)
  for (let i = 0; i < outLength; i++) {
    const t = i * ratio
    const i0 = Math.floor(t)
    const i1 = Math.min(i0 + 1, input.length - 1)
    const f = t - i0
    out[i] = input[i0] * (1 - f) + input[i1] * f
  }
  return out
}

/**
 * Streaming downsampler: any input rate to 16 kHz Int16, emitted as fixed 20 ms frames.
 * Keeps fractional position between calls so chunk boundaries are seamless.
 */
export class FrameDownsampler {
  private ratio: number
  private pending = new Float32Array(0)
  private t = 0
  private outFloat: number[] = []

  constructor(inputRate: number, private frameSamples = FRAME_SAMPLES) {
    this.ratio = inputRate / TARGET_RATE
  }

  /** Feed input samples; returns zero or more complete frames. */
  push(input: Float32Array): Int16Array[] {
    const merged = new Float32Array(this.pending.length + input.length)
    merged.set(this.pending)
    merged.set(input, this.pending.length)

    let t = this.t
    while (Math.floor(t) + 1 < merged.length) {
      const i = Math.floor(t)
      const f = t - i
      this.outFloat.push(merged[i] * (1 - f) + merged[i + 1] * f)
      t += this.ratio
    }
    const consumed = Math.min(Math.floor(t), merged.length)
    this.pending = merged.slice(consumed)
    this.t = t - consumed

    const frames: Int16Array[] = []
    while (this.outFloat.length >= this.frameSamples) {
      const chunk = this.outFloat.splice(0, this.frameSamples)
      frames.push(floatToInt16(Float32Array.from(chunk)))
    }
    return frames
  }
}

/** Root-mean-square level of float samples, 0..1. */
export function rms(input: Float32Array): number {
  if (input.length === 0) return 0
  let sum = 0
  for (let i = 0; i < input.length; i++) sum += input[i] * input[i]
  return Math.sqrt(sum / input.length)
}
