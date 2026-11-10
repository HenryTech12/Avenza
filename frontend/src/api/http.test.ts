import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, messageFromDetail, request, setUnauthorizedHandler } from './http'
import { deviceToken } from '../lib/settings'

const json = (status: number, body: unknown) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }))

describe('central HTTP client', () => {
  beforeEach(() => {
    deviceToken.value = 'tok_1'
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    setUnauthorizedHandler(null)
    deviceToken.value = null
  })

  it('sends the bearer token and no cookies', async () => {
    const f = vi.fn().mockReturnValue(json(200, { ok: true }))
    vi.stubGlobal('fetch', f)
    await request('/me', (d) => d)
    const [, init] = f.mock.calls[0] as [string, RequestInit]
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok_1')
    expect(init.credentials).toBe('omit')
  })

  it('skips the token for public calls and builds the query string', async () => {
    const f = vi.fn().mockReturnValue(json(200, {}))
    vi.stubGlobal('fetch', f)
    await request('/transfers', (d) => d, { auth: false, query: { limit: 25, start: undefined, end: 'a b' } })
    const [url, init] = f.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/transfers?limit=25&end=a%20b')
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined()
  })

  it('a 401 on an authenticated call runs the unauthorized handler and throws the backend message', async () => {
    const handler = vi.fn()
    setUnauthorizedHandler(handler)
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(json(401, { detail: 'device token required or invalid' })))
    await expect(request('/me', (d) => d)).rejects.toMatchObject({ status: 401, kind: 'unauthorized', message: 'device token required or invalid' })
    expect(handler).toHaveBeenCalledTimes(1)
  })

  it('maps 422 validation arrays and network failures', async () => {
    expect(messageFromDetail([{ loc: ['body', 'account_number'], msg: 'String should match pattern' }])).toBe('account_number: String should match pattern')
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('failed')))
    await expect(request('/me', (d) => d)).rejects.toBeInstanceOf(ApiError)
    await expect(request('/me', (d) => d)).rejects.toMatchObject({ status: 0, kind: 'network' })
  })
})
