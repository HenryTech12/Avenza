import { signal } from '@preact/signals'
import { getAudioContext } from './audioContext'

export class MicDeniedError extends Error {
  constructor(cause?: unknown) {
    super('Microphone permission denied')
    this.name = 'MicDeniedError'
    this.cause = cause
  }
}

/**
 * Mic capture: getUserMedia -> AudioWorklet -> 20 ms 16 kHz Int16 frames.
 * The stream stays open for the whole session; half-duplex is done by the `gate`,
 * which drops frames instead of closing the mic (no re-prompt, no warm-up).
 */
export class MicCapture {
  /** Smoothed mic level 0..1 for the ListeningOrb. */
  readonly level = signal(0)
  stream: MediaStream | null = null
  private node: AudioWorkletNode | null = null
  private source: MediaStreamAudioSourceNode | null = null
  private handlers = new Set<(frame: ArrayBuffer) => void>()
  private smooth = 0
  /** When false, frames are dropped and level reads 0. */
  gate = false

  onFrame(h: (frame: ArrayBuffer) => void): () => void {
    this.handlers.add(h)
    return () => this.handlers.delete(h)
  }

  private starting: Promise<void> | null = null

  start(): Promise<void> {
    if (this.stream && this.node) return Promise.resolve()
    this.starting ??= this.doStart().finally(() => {
      this.starting = null
    })
    return this.starting
  }

  private async doStart(): Promise<void> {
    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
      })
    } catch (e) {
      throw new MicDeniedError(e)
    }
    this.stream = stream
    const ctx = getAudioContext()
    await ctx.audioWorklet.addModule('/pcm-worklet.js')
    this.source = ctx.createMediaStreamSource(stream)
    this.node = new AudioWorkletNode(ctx, 'pcm-processor', { numberOfInputs: 1, numberOfOutputs: 0 })
    this.node.port.onmessage = (ev: MessageEvent<{ frame?: ArrayBuffer; level: number }>) => {
      const { frame, level } = ev.data
      const target = this.gate ? Math.min(1, level * 6) : 0
      // fast attack, slower release
      this.smooth += (target - this.smooth) * (target > this.smooth ? 0.6 : 0.15)
      this.level.value = this.smooth
      if (frame && this.gate) {
        for (const h of this.handlers) h(frame)
      }
    }
    this.source.connect(this.node)
  }

  stop(): void {
    this.node?.disconnect()
    this.source?.disconnect()
    this.stream?.getTracks().forEach((t) => t.stop())
    this.node = null
    this.source = null
    this.stream = null
    this.level.value = 0
  }
}
