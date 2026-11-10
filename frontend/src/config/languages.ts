import type { Lang } from '../protocol/messages'

export interface LanguageInfo {
  code: Lang
  name: string // name in its own language
  english: string
  enabled: boolean // only languages that pass testing may be offered
  speechLocale: string
}

export const languages: LanguageInfo[] = [
  { code: 'en', name: 'English', english: 'English', enabled: true, speechLocale: 'en-NG' },
  { code: 'yo', name: 'Yorùbá', english: 'Yoruba', enabled: false, speechLocale: 'yo-NG' },
  { code: 'ha', name: 'Hausa', english: 'Hausa', enabled: false, speechLocale: 'ha-NG' },
  { code: 'ig', name: 'Igbo', english: 'Igbo', enabled: false, speechLocale: 'ig-NG' },
]

export const speechProviders = [
  'Google Cloud Speech-to-Text',
  'Anthropic Claude (language understanding)',
  'A text-to-speech provider',
]
export const CONSENT_VERSION = '2026-11-v1'
