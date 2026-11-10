import { signal } from '@preact/signals'
import type { AudioChunk, ClientMessage, ServerMessage } from '../protocol/messages'
import { ScenarioRunner } from '../mocks/scenarioRunner'
import { env } from '../config/env'
import { Emitter } from './emitter'
import { logMessage } from './protocolLog'
import type { Transport, TransportStatus } from './Transport'

/** Runs a scripted scenario in the browser. No network. */
export class MockTransport implements Transport {
  readonly status = signal<TransportStatus>('closed')
  private emitter = new Emitter()
  private runner: ScenarioRunner
  private dropped = false

  constructor(scenarioId: string = env.MOCK_SCENARIO) {
    this.runner = new ScenarioRunner(
      {
        emit: (m) => this.deliver(m),
        drop: (ms) => this.simulateDrop(ms),
      },
      scenarioId,
    )
  }

  setScenario(id: string): void {
    this.runner.setScenario(id)
  }

  async connect(): Promise<void> {
    this.status.value = 'connecting'
    await new Promise((r) => setTimeout(r, 150))
    this.status.value = 'open'
  }

  close(): void {
    this.runner.stop()
    this.status.value = 'closed'
  }

  send(msg: ClientMessage): void {
    logMessage('out', msg.type)
    if (this.dropped) return
    this.runner.onClient(msg)
  }

  sendAudio(_frame: ArrayBuffer): void {
    // Audio is discarded in mock mode (and never stored).
  }

  on(handler: (msg: ServerMessage) => void): () => void {
    return this.emitter.on(handler)
  }

  onAudio(handler: (chunk: AudioChunk) => void): () => void {
    return this.emitter.onAudio(handler)
  }

  private deliver(m: ServerMessage): void {
    if (this.dropped) {
      // messages sent while "offline" are lost; the server re-syncs state after reconnect
      return
    }
    this.emitter.emit(m)
  }

  private simulateDrop(ms: number): void {
    this.dropped = true
    this.status.value = 'reconnecting'
    setTimeout(() => {
      this.dropped = false
      this.status.value = 'open'
      this.runner.resyncAfterReconnect()
    }, ms)
  }
}
