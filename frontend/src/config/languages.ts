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

// The processors the deployed backend really uses (10 Nov 2026). Keep in step with .env.forge.
export const speechProviders = [
  'Intron Sahara and YarnGPT (speech-to-text)',
  'YarnGPT (Avenza\'s voice)',
  'Huawei Cloud (language understanding)',
  "your browser's speech recognition, only while you set up",
]
export const CONSENT_VERSION = '2026-11-v2' // v2: real provider list, browser speech during set-up
