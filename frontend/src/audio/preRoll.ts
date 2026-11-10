/**
 * RAM-only ring buffer of the most recent mic frames. Never persisted.
 * Cleared after each utterance.
 */
export class PreRoll {
  private frames: ArrayBuffer[] = []
  constructor(private maxFrames: number) {}

  setMaxFrames(n: number): void {
    this.maxFrames = Math.max(1, n)
    this.trim()
  }

  push(frame: ArrayBuffer): void {
    this.frames.push(frame)
    this.trim()
  }

  /** Returns buffered frames in order and empties the buffer. */
  drain(): ArrayBuffer[] {
    const out = this.frames
    this.frames = []
    return out
  }

  clear(): void {
    this.frames = []
  }

  get length(): number {
    return this.frames.length
  }

  private trim(): void {
    if (this.frames.length > this.maxFrames) this.frames.splice(0, this.frames.length - this.maxFrames)
  }
}

/** Frames needed to cover `ms` of 20 ms frames. */
export const framesForMs = (ms: number): number => Math.ceil(ms / 20)
