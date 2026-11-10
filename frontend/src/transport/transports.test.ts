import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MockTransport } from './MockTransport'
import { WebSocketTransport, backoffDelay } from './WebSocketTransport'
import type { ServerMessage } from '../protocol/messages'

describe('backoff', () => {
  it('is 500, 1000, 2000, 4000 then capped at 4000', () => {
    expect([0, 1, 2, 3, 4, 9].map(backoffDelay)).toEqual([500, 1000, 2000, 4000, 4000, 4000])
  })
})

describe('MockTransport happy_path', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('runs session.start, utterance, yes, approval to SETTLED', async () => {
    const t = new MockTransport('happy_path')
    const got: ServerMessage[] = []
    t.on((m) => got.push(m))
    const p = t.connect()
    await vi.advanceTimersByTimeAsync(300)
    await p
    expect(t.status.value).toBe('open')
    t.send({ type: 'session.start', deviceToken: 'd', consentId: 'c', language: 'en' })
    await vi.advanceTimersByTimeAsync(300)
    expect(got.map((m) => m.type)).toEqual(['listening'])
    t.send({ type: 'utterance.start', sampleRate: 16000 })
    t.send({ type: 'utterance.end' })
    await vi.advanceTimersByTimeAsync(3000)
    const rb = got.find((m) => m.type === 'state.changed' && m.state === 'READBACK_PLAYED')
    expect(rb).toBeTruthy()
    expect(got.some((m) => m.type === 'transcript.final')).toBe(true)
    const id = (rb as Extract<ServerMessage, { type: 'state.changed' }>).transferId
    t.send({ type: 'confirm.response', transferId: id, answer: 'yes' })
    await vi.advanceTimersByTimeAsync(1000)
    expect(got.some((m) => m.type === 'approval.request')).toBe(true)
    // money only moves after an approval.response
    expect(got.some((m) => m.type === 'state.changed' && m.state === 'SETTLED')).toBe(false)
    t.send({ type: 'approval.response', transferId: id, assertion: {} as never })
    await vi.advanceTimersByTimeAsync(5000)
    const settled = got.find((m) => m.type === 'state.changed' && m.state === 'SETTLED') as Extract<ServerMessage, { type: 'state.changed' }>
    expect(settled.draft?.reference).toMatch(/^AVZ/)
    expect(settled.draft?.amountKobo).toBe(500000)
  })

  it('say_no cancels and never asks for a fingerprint', async () => {
    const t = new MockTransport('say_no')
    const got: ServerMessage[] = []
    t.on((m) => got.push(m))
    t.send({ type: 'session.start', deviceToken: 'd', consentId: 'c', language: 'en' })
    t.send({ type: 'utterance.end' })
    await vi.advanceTimersByTimeAsync(3000)
    t.send({ type: 'utterance.end' }) // spoken reply = scripted "no"
    await vi.advanceTimersByTimeAsync(1000)
    expect(got.some((m) => m.type === 'state.changed' && m.state === 'CANCELLED')).toBe(true)
    expect(got.some((m) => m.type === 'approval.request')).toBe(false)
  })
})

describe('WebSocketTransport (live wire format)', () => {
  type Internals = {
    onMessage(d: unknown): void
    on(h: (m: ServerMessage) => void): void
    onAudio(h: (c: { pcm: Int16Array; sampleRate: number; final: boolean }) => void): void
    inbox: Promise<void>
  }

  it('maps snake_case events, ignores unknown and malformed ones, keeps order', async () => {
    const t = new WebSocketTransport('wss://x') as unknown as Internals
    const msgs: ServerMessage[] = []
    const chunks: number[] = []
    t.on((m) => msgs.push(m))
    t.onAudio((c) => chunks.push(c.pcm.length))
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    const pcm = btoa(String.fromCharCode(1, 0, 2, 0, 3, 0, 4, 0))
    t.onMessage(JSON.stringify({ type: 'audio.stream', data: pcm, sample_rate: 24000 }))
    t.onMessage(JSON.stringify({ type: 'nope' })) // unknown: ignored
    t.onMessage('{bad json') // malformed: dropped
    t.onMessage(new Int16Array([9]).buffer) // the backend never sends binary frames: ignored
    t.onMessage(JSON.stringify({ type: 'prompt.play', id: 'readback', text: 'Send five thousand naira', audio_url: null, warnings: ['duplicate'] }))
    t.onMessage(JSON.stringify({ type: 'error', code: 'unclear', prompt_id: 'unclear', message: 'x' }))
    t.onMessage(JSON.stringify({ type: 'listening', tone: true }))
    await t.inbox
    expect(chunks).toEqual([4])
    expect(msgs.map((m) => m.type)).toEqual(['audio.stream', 'prompt.play', 'error', 'listening'])
    const play = msgs[1] as Extract<ServerMessage, { type: 'prompt.play' }>
    expect(play.text).toBe('Send five thousand naira')
    expect(play.warnings).toEqual(['duplicate'])
    warn.mockRestore()
  })

  it('sends session.start and a tapped answer in the backend format', () => {
    const sent: string[] = []
    const t = new WebSocketTransport('wss://x') as unknown as { ws: unknown; send(m: unknown): void }
    t.ws = { readyState: WebSocket.OPEN, send: (d: string) => sent.push(d) }
    t.send({ type: 'session.start', deviceToken: 'tok', consentId: 'cns_1', language: 'en' })
    t.send({ type: 'confirm.response', transferId: 'tr_1', answer: 'yes' })
    t.send({ type: 'utterance.start', sampleRate: 16000 })
    expect(sent.map((x) => JSON.parse(x))).toEqual([
      { type: 'session.start', device_token: 'tok', consent_id: 'cns_1', language: 'en' },
      { type: 'utterance.text', text: 'yes', final: true },
      { type: 'utterance.start', sample_rate: 16000 },
    ])
  })
})
