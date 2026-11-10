import { env } from '../config/env'
import { api } from '../api'
import { createEnricher } from './liveEnrich'
import { MockTransport } from './MockTransport'
import { WebSocketTransport } from './WebSocketTransport'
import type { Transport } from './Transport'

export type { Transport, TransportStatus } from './Transport'
export { protocolLog } from './protocolLog'

/** The only place that knows which transport is in use. */
export function createTransport(): Transport {
  return env.BACKEND_MODE === 'live' ? new WebSocketTransport(env.WS_URL, createEnricher(api)) : new MockTransport(env.MOCK_SCENARIO)
}
