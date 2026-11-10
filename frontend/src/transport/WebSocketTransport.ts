import { signal } from '@preact/signals'
import type { AudioChunk, ClientMessage, ServerMessage } from '../protocol/messages'
import { encodeClientMessage, parseWireMessage } from '../protocol/wire'
import { Emitter } from './emitter'
import { logMessage } from './protocolLog'
import type { Transport, TransportStatus } from './Transport'

export const BACKOFF_MS = [500, 1000, 2000, 4000]

export function backoffDelay(attempt: number): number {
  return BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)]
}

export type Enricher = (msg: ServerMessage) => Promise<ServerMessage>

/** Real transport: snake_case JSON control messages and binary PCM frames to the server (src/protocol/wire.ts). */
export class WebSocketTransport implements Transport {
  readonly status = signal<TransportStatus>('closed')
  private ws: WebSocket | null = null
  private emitter = new Emitter()
  private attempt = 0
  private closedByUs = false
  private inbox: Promise<void> = Promise.resolve() // messages are handled strictly in arrival order
  private lastSessionStart: ClientMessage | null = null
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null

  constructor(
    private url: string,
    private enrich: Enricher = async (m) => m,
  ) {}

  connect(): Promise<void> {
    this.closedByUs = false
    this.status.value = this.attempt === 0 ? 'connecting' : 'reconnecting'
    return new Promise((resolve, reject) => {
      let settled = false
      let ws: WebSocket
      try {
        ws = new WebSocket(this.url)
      } catch (e) {
        this.scheduleReconnect()
        reject(e)
        return
      }
      ws.binaryType = 'arraybuffer'
      this.ws = ws
      ws.onopen = () => {
        this.attempt = 0
        this.status.value = 'open'
        // re-send session.start so the server restores the session
        if (this.lastSessionStart) ws.send(JSON.stringify(encodeClientMessage(this.lastSessionStart)))
        settled = true
        resolve()
      }
      ws.onmessage = (ev) => this.onMessage(ev.data)
      ws.onerror = () => {
        if (!settled) {
          settled = true
          reject(new Error('WebSocket connection failed'))
        }
      }
      ws.onclose = () => {
        if (this.closedByUs) {
          this.status.value = 'closed'
          return
        }
        if (!settled) {
          settled = true
          reject(new Error('WebSocket closed'))
        }
        this.scheduleReconnect()
      }
    })
  }

  private scheduleReconnect(): void {
    this.status.value = 'reconnecting'
    const delay = backoffDelay(this.attempt++)
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    this.reconnectTimer = setTimeout(() => {
      this.connect().catch(() => undefined)
    }, delay)
  }

  close(): void {
    this.closedByUs = true
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    this.ws?.close()
    this.status.value = 'closed'
  }

  send(msg: ClientMessage): void {
    if (msg.type === 'session.start') this.lastSessionStart = msg
    logMessage('out', msg.type)
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(encodeClientMessage(msg)))
  }

  sendAudio(frame: ArrayBuffer): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(frame)
  }

  on(handler: (msg: ServerMessage) => void): () => void {
    return this.emitter.on(handler)
  }

  onAudio(handler: (chunk: AudioChunk) => void): () => void {
    return this.emitter.onAudio(handler)
  }

  private onMessage(data: unknown): void {
    if (typeof data !== 'string') return // the backend sends audio as base64 inside JSON, never as binary frames
    const r = parseWireMessage(data)
    if (!r.ok) {
      if (r.reason === 'malformed') console.warn('[avenza] dropped malformed message:', r.detail)
      return
    }
    this.inbox = this.inbox
      .then(async () => {
        const msg = await this.enrich(r.msg)
        if (r.audio) this.emitter.emitAudio(r.audio)
        this.emitter.emit(msg)
      })
      .catch((e) => console.warn('[avenza] message handler failed', e))
  }
}
