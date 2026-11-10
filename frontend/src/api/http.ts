import { env } from '../config/env'
import { deviceToken } from '../lib/settings'

/** An HTTP or network failure, with the backend's own message when there is one. */
export class ApiError extends Error {
  constructor(
    public status: number, // 0 = network error or timeout
    message: string,
    public kind: 'network' | 'timeout' | 'unauthorized' | 'validation' | 'conflict' | 'not-found' | 'server' | 'client' = 'client',
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

type UnauthorizedHandler = () => void
let onUnauthorized: UnauthorizedHandler | null = null

/** The session registers what happens on a 401 (forget the device, send the customer to enrol again). */
export function setUnauthorizedHandler(fn: UnauthorizedHandler | null): void {
  onUnauthorized = fn
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  body?: unknown
  auth?: boolean // send the device token (default true when we have one)
  query?: Record<string, string | number | undefined>
  timeoutMs?: number
}

/** FastAPI errors: `{detail: "text"}` or `{detail: [{loc, msg}]}` for 422. */
export function messageFromDetail(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        const e = d as { loc?: unknown[]; msg?: string }
        const field = Array.isArray(e.loc) ? e.loc.filter((p) => p !== 'body').join('.') : ''
        return field ? `${field}: ${e.msg ?? 'invalid'}` : (e.msg ?? 'invalid')
      })
      .join('; ')
  }
  return ''
}

/**
 * The one HTTP client. Adds the device token, a timeout and uniform errors; a 401 on an authenticated call
 * triggers the unauthorized handler (the device is no longer known to the backend).
 */
export async function request<T>(path: string, parse: (data: unknown) => T, opts: RequestOptions = {}): Promise<T> {
  const { method = opts.body === undefined ? 'GET' : 'POST', body, query, timeoutMs = 10_000 } = opts
  const token = deviceToken.value
  const authed = opts.auth !== false && !!token
  const qs = query
    ? '?' + Object.entries(query).filter(([, v]) => v !== undefined && v !== '').map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join('&')
    : ''
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (authed) headers.Authorization = `Bearer ${token}`

  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  let res: Response
  try {
    res = await fetch(`${env.API_BASE_URL}${path}${qs === '?' ? '' : qs}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: ctrl.signal,
      credentials: 'omit', // bearer token, not cookies
    })
  } catch (e) {
    const aborted = (e as { name?: string }).name === 'AbortError'
    throw new ApiError(0, aborted ? 'The request timed out' : 'Could not reach the server', aborted ? 'timeout' : 'network')
  } finally {
    clearTimeout(timer)
  }

  if (!res.ok) {
    let message = ''
    try {
      message = messageFromDetail(((await res.json()) as { detail?: unknown }).detail)
    } catch {
      /* not JSON */
    }
    if (res.status === 401 && authed) onUnauthorized?.()
    const kind =
      res.status === 401 ? 'unauthorized' : res.status === 404 ? 'not-found' : res.status === 409 ? 'conflict' : res.status === 422 ? 'validation' : res.status >= 500 ? 'server' : 'client'
    throw new ApiError(res.status, message || `Request failed (${res.status})`, kind)
  }
  try {
    return parse(await res.json())
  } catch (e) {
    throw new ApiError(res.status, `Unexpected response from ${path}: ${(e as Error).message}`, 'server')
  }
}
