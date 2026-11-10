import { language } from '../lib/settings'
import en from './en.json'
import yo from './yo.json'
import ha from './ha.json'
import ig from './ig.json'
import type { Lang } from '../protocol/messages'

type Dict = Record<string, string>
const dicts: Record<Lang, Dict> = { en, yo, ha, ig }

export type Key = keyof typeof en

/** Translate. Reads the language signal, so components re-render on change. English fallback. */
export function t(key: Key | (string & {}), params?: Record<string, string | number>): string {
  const lang = language.value
  let s = dicts[lang]?.[key] ?? (en as Dict)[key] ?? key
  if (params) for (const [k, v] of Object.entries(params)) s = s.replaceAll(`{${k}}`, String(v))
  return s
}
