import { env } from '../config/env'
import type { ApiClient } from './ApiClient'
import { HttpApiClient } from './HttpApiClient'
import { MockApiClient } from './MockApiClient'

export type { ApiClient } from './ApiClient'
export { ApiError, setUnauthorizedHandler } from './http'

export function createApiClient(): ApiClient {
  return env.BACKEND_MODE === 'live' ? new HttpApiClient() : new MockApiClient()
}

/** One client for the whole app (the mock one keeps its small in-memory state). */
export const api: ApiClient = createApiClient()
