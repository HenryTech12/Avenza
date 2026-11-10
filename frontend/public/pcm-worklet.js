// AudioWorklet: downsample mic input to 16 kHz, convert to Int16, post 20 ms frames (320 samples / 640 bytes)
// plus a block RMS level. Kept dependency-free (plain JS in /public) so it loads identically in dev and prod.
// The same algorithm lives in src/audio/pcm.ts (FrameDownsampler) and is unit-tested there; src/audio/worklet.test.ts
// runs this file against it to keep them in sync.
/* global sampleRate, registerProcessor, AudioWorkletProcessor */
const TARGET_RATE = 16000
const FRAME_SAMPLES = 320

class FrameDownsampler {
  constructor(inputRate, frameSamples = FRAME_SAMPLES) {
    this.ratio = inputRate / TARGET_RATE
    this.frameSamples = frameSamples
    this.pending = new Float32Array(0)
    this.t = 0
    this.outFloat = []
  }
  push(input) {
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
    const frames = []
    while (this.outFloat.length >= this.frameSamples) {
      const chunk = this.outFloat.splice(0, this.frameSamples)
      const out = new Int16Array(chunk.length)
      for (let i = 0; i < chunk.length; i++) {
        const s = Math.max(-1, Math.min(1, chunk[i]))
        out[i] = s < 0 ? Math.round(s * 0x8000) : Math.round(s * 0x7fff)
      }
      frames.push(out)
    }
    return frames
  }
}

function rms(input) {
  if (input.length === 0) return 0
  let sum = 0
  for (let i = 0; i < input.length; i++) sum += input[i] * input[i]
  return Math.sqrt(sum / input.length)
}

class PcmProcessor extends AudioWorkletProcessor {
  constructor() {
    super()
    this.down = new FrameDownsampler(sampleRate)
  }
  process(inputs) {
    const channel = inputs[0] && inputs[0][0]
    if (!channel) return true
    const level = rms(channel)
    const frames = this.down.push(channel)
    for (const f of frames) {
      const buf = f.buffer
      this.port.postMessage({ frame: buf, level }, [buf])
    }
    if (frames.length === 0) this.port.postMessage({ level })
    return true
  }
}

registerProcessor('pcm-processor', PcmProcessor)
