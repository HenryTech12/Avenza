import { language } from '../../lib/settings'
import { languageBeta } from '../../session/session'
import { languages } from '../../config/languages'
import { t } from '../../i18n'
import styles from './LanguageBadge.module.css'

/** Shown while Avenza speaks Hausa, Igbo or Yoruba: those are beta until a native speaker checks them. */
export function LanguageBadge() {
  const code = language.value
  if (code === 'en' && !languageBeta.value) return null
  const name = languages.find((l) => l.code === code)?.name ?? code
  return (
    <span class={styles.badge} title={t('lang.betaLabel', { name })}>
      {name} · {t('lang.beta')}
      <span class="sr-only">{t('lang.betaLabel', { name })}</span>
    </span>
  )
}
