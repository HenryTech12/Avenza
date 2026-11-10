import { signal, effect } from '@preact/signals'
import type { Lang } from '../protocol/messages'

/**
 * The only things persisted: language, consentId, deviceToken, onboardingComplete, theme, highContrast.
 * deviceToken is the bearer token the backend issues at enrolment (it identifies this device; it cannot approve a payment, only the fingerprint can).
 * Never audio, transcripts, PINs or card data.
 */
export type Theme = 'system' | 'dark' | 'light'

const KEY = 'avenza.settings.v1'

interface Persisted {
  language: Lang
  consentId: string | null
  deviceToken: string | null
  onboardingComplete: boolean
  theme: Theme
  highContrast: boolean
}

const defaults: Persisted = {
  language: 'en',
  consentId: null,
  deviceToken: null,
  onboardingComplete: false,
  theme: 'system',
  highContrast: false,
}

function load(): Persisted {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) ?? '{}') as Partial<Persisted>
    return {
      language: (['en', 'yo', 'ha', 'ig'] as const).includes(raw.language as Lang) ? (raw.language as Lang) : defaults.language,
      consentId: typeof raw.consentId === 'string' ? raw.consentId : null,
      deviceToken: typeof raw.deviceToken === 'string' ? raw.deviceToken : null,
      onboardingComplete: raw.onboardingComplete === true,
      theme: raw.theme === 'dark' || raw.theme === 'light' ? raw.theme : 'system',
      highContrast: raw.highContrast === true,
    }
  } catch {
    return { ...defaults }
  }
}

const initial = load()
export const language = signal<Lang>(initial.language)
export const consentId = signal<string | null>(initial.consentId)
export const deviceToken = signal<string | null>(initial.deviceToken)
export const onboardingComplete = signal<boolean>(initial.onboardingComplete)
export const theme = signal<Theme>(initial.theme)
export const highContrast = signal<boolean>(initial.highContrast)

function save(): void {
  const data: Persisted = {
    language: language.value,
    consentId: consentId.value,
    deviceToken: deviceToken.value,
    onboardingComplete: onboardingComplete.value,
    theme: theme.value,
    highContrast: highContrast.value,
  }
  try {
    localStorage.setItem(KEY, JSON.stringify(data))
  } catch {
    /* storage unavailable: keep running in memory */
  }
}

export function clearSettings(): void {
  try {
    localStorage.removeItem(KEY)
  } catch {
    /* ignore */
  }
  language.value = defaults.language
  consentId.value = null
  deviceToken.value = null
  onboardingComplete.value = false
  theme.value = defaults.theme
  highContrast.value = defaults.highContrast
}

/** Persist + apply to <html>. Call once at startup. */
export function startSettingsEffects(): () => void {
  const mq = window.matchMedia?.('(prefers-color-scheme: light)')
  const stops = [
    effect(() => {
      save()
    }),
    effect(() => {
      const root = document.documentElement
      root.lang = language.value
      if (theme.value === 'system') root.removeAttribute('data-theme')
      else root.dataset.theme = theme.value
      const effective = theme.value === 'system' ? (mq?.matches ? 'light' : 'dark') : theme.value
      root.dataset.effectiveTheme = effective
      if (highContrast.value) root.dataset.contrast = 'high'
      else root.removeAttribute('data-contrast')
    }),
  ]
  const onChange = () => {
    theme.value = theme.value // re-run the effect
    document.documentElement.dataset.effectiveTheme =
      theme.value === 'system' ? (mq?.matches ? 'light' : 'dark') : theme.value
  }
  mq?.addEventListener?.('change', onChange)
  return () => {
    stops.forEach((s) => s())
    mq?.removeEventListener?.('change', onChange)
  }
}
