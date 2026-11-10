import type { AudioChunk, ServerMessage } from '../protocol/messages'
import { logMessage } from './protocolLog'

/** Small shared handler registry used by both transports. */
export class Emitter {
  private handlers = new Set<(m: ServerMessage) => void>()
  private audioHandlers = new Set<(c: AudioChunk) => void>()

  on(h: (m: ServerMessage) => void): () => void {
    this.handlers.add(h)
    return () => this.handlers.delete(h)
  }
  onAudio(h: (c: AudioChunk) => void): () => void {
    this.audioHandlers.add(h)
    return () => this.audioHandlers.delete(h)
  }
  emit(m: ServerMessage): void {
    logMessage('in', m.type)
    for (const h of [...this.handlers]) {
      try {
        h(m)
      } catch (e) {
        console.error('[avenza] handler error', e)
      }
    }
  }
  emitAudio(c: AudioChunk): void {
    for (const h of [...this.audioHandlers]) {
      try {
        h(c)
      } catch (e) {
        console.error('[avenza] audio handler error', e)
      }
    }
  }
}
