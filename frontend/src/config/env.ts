import { z } from 'zod'

const schema = z.object({
  BACKEND_MODE: z.enum(['mock', 'live']).default('mock'),
  API_BASE_URL: z.string().default(''), // empty = same origin as the app
  WS_URL: z.string().default(''), // empty = derived from API_BASE_URL
  MOCK_SCENARIO: z.string().default('happy_path'),
  DEV_PANEL: z.boolean().default(false),
})

const raw = import.meta.env
const parsed = schema.parse({
  BACKEND_MODE: raw.VITE_BACKEND_MODE || undefined,
  API_BASE_URL: raw.VITE_API_BASE_URL || undefined,
  WS_URL: raw.VITE_WS_URL || undefined,
  MOCK_SCENARIO: raw.VITE_MOCK_SCENARIO || undefined,
  DEV_PANEL: raw.VITE_DEV_PANEL === 'true',
})

const apiBase = parsed.API_BASE_URL.replace(/\/+$/, '')

function deriveWsUrl(): string {
  if (parsed.WS_URL) return parsed.WS_URL
  const base = apiBase || (typeof location !== 'undefined' ? location.origin : 'http://localhost')
  return `${base.replace(/^http/, 'ws')}/ws`
}

const OVERRIDE_KEY = 'avenza.devOverride'

export interface Override {
  BACKEND_MODE?: 'mock' | 'live'
  MOCK_SCENARIO?: string
}

export function readOverride(): Override {
  try {
    return JSON.parse(sessionStorage.getItem(OVERRIDE_KEY) ?? '{}') as Override
  } catch {
    return {}
  }
}

/** Dev panel overrides live in sessionStorage only. */
export function writeOverride(o: Override): void {
  sessionStorage.setItem(OVERRIDE_KEY, JSON.stringify({ ...readOverride(), ...o }))
}

export function clearOverride(): void {
  sessionStorage.removeItem(OVERRIDE_KEY)
}

export const env = {
  get BACKEND_MODE(): 'mock' | 'live' {
    return (parsed.DEV_PANEL ? readOverride().BACKEND_MODE : undefined) ?? parsed.BACKEND_MODE
  },
  get MOCK_SCENARIO(): string {
    return (parsed.DEV_PANEL ? readOverride().MOCK_SCENARIO : undefined) ?? parsed.MOCK_SCENARIO
  },
  /** Backend REST base URL (`VITE_API_BASE_URL`). Empty means same origin. */
  API_BASE_URL: apiBase,
  WS_URL: deriveWsUrl(),
  DEV_PANEL: parsed.DEV_PANEL,
  hasOverride(): boolean {
    const o = readOverride()
    return parsed.DEV_PANEL && (!!o.BACKEND_MODE || !!o.MOCK_SCENARIO)
  },
}
