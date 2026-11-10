import { signal } from '@preact/signals'
import { int16ToFloat, resampleLinear } from './pcm'

/** The slice of AudioContext the player needs (also what tests fake). */
export interface CtxLike {
  readonly sampleRate: number
  readonly currentTime: number
  readonly destination: unknown
  createBuffer(channels: number, length: number, sampleRate: number): BufferLike
  createBufferSource(): SourceLike
}
export interface BufferLike {
  readonly duration: number
  copyToChannel(data: Float32Array, channel: number): void
}
export interface SourceLike {
  buffer: unknown
  onended: (() => void) | null
  connect(dest: unknown): unknown
  start(when?: number): void
  stop(): void
}

export interface PlayerDeps {
  getContext(): CtxLike
  /** Speak text when no audio file exists. Resolves when finished. */
  speakText?(text: string, lang: string): Promise<void>
  jitterMs?: number
}

interface Task {
  label: string
  run(): Promise<void>
  cancel(): void
}

const JITTER_MS_DEFAULT = 100

/**
 * Single playback queue. Cached prompts, tones, live PCM and spoken fallbacks all
 * pass through here, one at a time, so nothing ever overlaps.
 */
export class Player {
  readonly isSpeaking = signal(false)
  readonly lastStartedLabel = signal('')
  private queue: Task[] = []
  private current: Task | null = null
  private idleHandlers = new Set<() => void>()
  private startHandlers = new Set<(label: string) => void>()
  private openStream: PcmStreamTask | null = null
  private generation = 0

  constructor(private deps: PlayerDeps) {}

  /** Called whenever the queue drains. */
  onIdle(cb: () => void): () => void {
    this.idleHandlers.add(cb)
    return () => this.idleHandlers.delete(cb)
  }

  /** Called when any item starts producing sound (used by latency tracking). */
  onSoundStart(cb: (label: string) => void): () => void {
    this.startHandlers.add(cb)
    return () => this.startHandlers.delete(cb)
  }

  get idle(): boolean {
    return !this.current && this.queue.length === 0
  }

  playBuffer(buffer: unknown, label = 'buffer'): Promise<void> {
    return this.enqueue(new BufferTask(this.deps, label, buffer, () => this.notifyStart(label)))
  }

  speak(text: string, lang = 'en-NG', label = 'speech'): Promise<void> {
    return this.enqueue(new SpeechTask(this.deps, label, text, lang, () => this.notifyStart(label)))
  }

  /** Add a live PCM chunk. A stream stays open until a chunk with `final` arrives. */
  pushPcm(pcm: Int16Array, sampleRate: number, final: boolean): void {
    if (!this.openStream) {
      const t = new PcmStreamTask(this.deps, () => this.notifyStart('live'))
      this.openStream = t
      void this.enqueue(t)
    }
    this.openStream.push(pcm, sampleRate, final)
    if (final) this.openStream = null
  }

  /** Drop everything queued and stop what is playing. */
  stop(): void {
    this.generation++
    const q = this.queue
    this.queue = []
    this.openStream = null
    q.forEach((t) => t.cancel())
    this.current?.cancel()
  }

  private notifyStart(label: string): void {
    this.lastStartedLabel.value = label
    this.startHandlers.forEach((h) => h(label))
  }

  private enqueue(task: Task): Promise<void> {
    return new Promise<void>((resolve) => {
      const wrapped: Task = {
        label: task.label,
        run: () => task.run().finally(resolve),
        cancel: () => {
          task.cancel()
          resolve()
        },
      }
      this.queue.push(wrapped)
      this.isSpeaking.value = true
      void this.pump()
    })
  }

  private async pump(): Promise<void> {
    if (this.current) return
    const next = this.queue.shift()
    if (!next) return
    this.current = next
    const gen = this.generation
    try {
      await next.run()
    } catch (e) {
      console.warn('[avenza] playback task failed', next.label, e)
    }
    if (gen === this.generation || this.current === next) this.current = null
    if (this.queue.length > 0) {
      void this.pump()
    } else {
      this.isSpeaking.value = false
      this.idleHandlers.forEach((h) => h())
    }
  }
}

class BufferTask implements Task {
  private src: SourceLike | null = null
  private done: (() => void) | null = null
  constructor(
    private deps: PlayerDeps,
    readonly label: string,
    private buffer: unknown,
    private started: () => void,
  ) {}
  run(): Promise<void> {
    return new Promise<void>((resolve) => {
      const ctx = this.deps.getContext()
      const src = ctx.createBufferSource()
      this.src = src
      this.done = resolve
      src.buffer = this.buffer
      src.connect(ctx.destination)
      src.onended = () => resolve()
      src.start()
      this.started()
    })
  }
  cancel(): void {
    try {
      this.src?.stop()
    } catch {
      /* already stopped */
    }
    this.done?.()
  }
}

class SpeechTask implements Task {
  private done: (() => void) | null = null
  constructor(
    private deps: PlayerDeps,
    readonly label: string,
    private text: string,
    private lang: string,
    private started: () => void,
  ) {}
  async run(): Promise<void> {
    if (!this.deps.speakText) return
    this.started()
    await Promise.race([
      this.deps.speakText(this.text, this.lang),
      new Promise<void>((r) => {
        this.done = r
      }),
    ])
  }
  cancel(): void {
    this.done?.()
    if (typeof speechSynthesis !== 'undefined') speechSynthesis.cancel()
  }
}

class PcmStreamTask implements Task {
  readonly label = 'live'
  private chunks: Array<{ pcm: Int16Array; rate: number }> = []
  private final = false
  private wake: (() => void) | null = null
  private cancelled = false
  private sources: SourceLike[] = []
  private lastEnded: Promise<void> = Promise.resolve()

  constructor(
    private deps: PlayerDeps,
    private started: () => void,
  ) {}

  push(pcm: Int16Array, rate: number, final: boolean): void {
    if (pcm.length > 0) this.chunks.push({ pcm, rate })
    if (final) this.final = true
    this.wake?.()
  }

  async run(): Promise<void> {
    const ctx = this.deps.getContext()
    const jitter = (this.deps.jitterMs ?? JITTER_MS_DEFAULT) / 1000
    let nextStart = 0
    let first = true
    while (!this.cancelled) {
      const c = this.chunks.shift()
      if (!c) {
        if (this.final) break
        await new Promise<void>((r) => (this.wake = r))
        this.wake = null
        continue
      }
      const floats = resampleLinear(int16ToFloat(c.pcm), c.rate, ctx.sampleRate)
      const buf = ctx.createBuffer(1, floats.length, ctx.sampleRate)
      buf.copyToChannel(floats, 0)
      const src = ctx.createBufferSource()
      src.buffer = buf
      src.connect(ctx.destination)
      const now = ctx.currentTime
      // first chunk waits one jitter buffer; later chunks queue gaplessly (or catch up after an underrun)
      nextStart = first ? now + jitter : Math.max(nextStart, now)
      src.start(nextStart)
      this.sources.push(src)
      this.lastEnded = new Promise<void>((r) => (src.onended = () => r()))
      nextStart += buf.duration
      if (first) {
        first = false
        this.started()
      }
    }
    await this.lastEnded
  }

  cancel(): void {
    this.cancelled = true
    this.final = true
    this.sources.forEach((s) => {
      try {
        s.stop()
      } catch {
        /* ended */
      }
    })
    this.wake?.()
  }
}
