import type { ReadonlySignal } from '@preact/signals'
import type { AudioChunk, ClientMessage, ServerMessage } from '../protocol/messages'

export type TransportStatus = 'connecting' | 'open' | 'reconnecting' | 'closed'

export interface Transport {
  connect(): Promise<void>
  close(): void
  send(msg: ClientMessage): void
  sendAudio(frame: ArrayBuffer): void
  on(handler: (msg: ServerMessage) => void): () => void
  onAudio(handler: (chunk: AudioChunk) => void): () => void
  status: ReadonlySignal<TransportStatus>
}
