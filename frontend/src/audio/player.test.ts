import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Player, type CtxLike, type SourceLike } from './player'

/** Fake context: each source "plays" for its buffer duration using fake timers. */
function makeCtx(events: string[]) {
  let now = 0
  const ctx: CtxLike = {
    sampleRate: 48000,
    get currentTime() {
      return now
    },
    destination: {},
    createBuffer: (_c, length, rate) => ({ duration: length / rate, copyToChannel: () => undefined }),
    createBufferSource: () => {
      let id = ++counter
      const s: SourceLike = {
        buffer: null,
        onended: null,
        connect: () => undefined,
        start() {
          events.push(`start:${(s.buffer as { name?: string })?.name ?? id}`)
          const dur = ((s.buffer as { duration: number }).duration ?? 0.1) * 1000
          setTimeout(() => {
            events.push(`end:${(s.buffer as { name?: string })?.name ?? id}`)
            s.onended?.()
          }, dur)
        },
        stop() {},
      }
      return s
    },
  }
  let counter = 0
  return { ctx, advance: (ms: number) => (now += ms / 1000) }
}

const clip = (name: string, seconds: number) => ({ name, duration: seconds })

describe('Player queue', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('plays items strictly in order with no overlap', async () => {
    const events: string[] = []
    const { ctx } = makeCtx(events)
    const p = new Player({ getContext: () => ctx })
    void p.playBuffer(clip('a', 0.5))
    void p.playBuffer(clip('b', 0.3))
    void p.playBuffer(clip('c', 0.2))
    await vi.advanceTimersByTimeAsync(2000)
    expect(events).toEqual(['start:a', 'end:a', 'start:b', 'end:b', 'start:c', 'end:c'])
  })

  it('reports isSpeaking and fires onIdle once when drained', async () => {
    const events: string[] = []
    const { ctx } = makeCtx(events)
    const p = new Player({ getContext: () => ctx })
    const idle = vi.fn()
    p.onIdle(idle)
    expect(p.isSpeaking.value).toBe(false)
    void p.playBuffer(clip('a', 0.2))
    void p.playBuffer(clip('b', 0.2))
    expect(p.isSpeaking.value).toBe(true)
    await vi.advanceTimersByTimeAsync(1000)
    expect(p.isSpeaking.value).toBe(false)
    expect(idle).toHaveBeenCalledTimes(1)
  })

  it('a prompt queued behind a live stream waits for the stream to finish', async () => {
    const events: string[] = []
    const { ctx } = makeCtx(events)
    const p = new Player({ getContext: () => ctx })
    p.pushPcm(new Int16Array(4800), 48000, false) // 0.1 s
    void p.playBuffer(clip('after', 0.1))
    p.pushPcm(new Int16Array(4800), 48000, true) // 0.1 s, final
    await vi.advanceTimersByTimeAsync(2000)
    const afterStart = events.indexOf('start:after')
    const lastLiveEnd = events.map((e, i) => (e.startsWith('end:') && e !== 'end:after' ? i : -1)).reduce((a, b) => Math.max(a, b))
    expect(afterStart).toBeGreaterThan(lastLiveEnd)
  })

  it('stop() drops queued items', async () => {
    const events: string[] = []
    const { ctx } = makeCtx(events)
    const p = new Player({ getContext: () => ctx })
    void p.playBuffer(clip('a', 0.5))
    void p.playBuffer(clip('b', 0.5))
    p.stop()
    await vi.advanceTimersByTimeAsync(2000)
    expect(events).not.toContain('start:b')
  })

  it('speech fallback uses speakText in order', async () => {
    const events: string[] = []
    const { ctx } = makeCtx(events)
    const speakText = vi.fn(async (t: string) => {
      events.push(`say:${t}`)
    })
    const p = new Player({ getContext: () => ctx, speakText })
    void p.speak('hello')
    void p.playBuffer(clip('a', 0.1))
    await vi.advanceTimersByTimeAsync(1000)
    expect(events.slice(0, 2)).toEqual(['say:hello', 'start:a'])
  })
})
