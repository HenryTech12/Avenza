import type { Lang } from '../protocol/messages'

export interface LanguageInfo {
  code: Lang
  name: string // name in its own language
  english: string
  enabled: boolean // only languages that pass testing may be offered
  beta?: boolean // offered, but Avenza's words are unverified by a native speaker
  speechLocale: string
}

export const languages: LanguageInfo[] = [
  { code: 'en', name: 'English', english: 'English', enabled: true, speechLocale: 'en-NG' },
  { code: 'yo', name: 'Yorùbá', english: 'Yoruba', enabled: true, beta: true, speechLocale: 'yo-NG' },
  { code: 'ha', name: 'Hausa', english: 'Hausa', enabled: true, beta: true, speechLocale: 'ha-NG' },
  { code: 'ig', name: 'Igbo', english: 'Igbo', enabled: true, beta: true, speechLocale: 'ig-NG' },
]

// The processors the deployed backend really uses (10 Nov 2026). Keep in step with .env.forge.
export const speechProviders = [
  'Intron Sahara and YarnGPT (speech-to-text)',
  'YarnGPT (Avenza\'s voice)',
  'Huawei Cloud (language understanding)',
  "your browser's speech recognition, only while you set up",
]
export const CONSENT_VERSION = '2026-11-v2' // v2: real provider list, browser speech during set-up
