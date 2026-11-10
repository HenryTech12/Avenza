import { useEffect, useRef } from 'preact/hooks'
import { useLocation } from 'preact-iso'
import { languages, chooseLanguage, language } from '../../session/session'
import { t } from '../../i18n'
import type { Lang } from '../../protocol/messages'
import styles from './Language.module.css'

const titles = ['Choose your language', 'Yan èdè rẹ', 'Zaɓi harshenka', 'Họrọ asụsụ gị']

export function Language() {
  const { route } = useLocation()
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => heading.current?.focus({ preventScroll: true }), [])

  const pick = async (code: Lang) => {
    await chooseLanguage(code)
    route('/onboarding/consent')
  }

  return (
    <main class="page">
      <header class={styles.head}>
        <h1 tabIndex={-1} ref={heading}>
          {t('language.title')}
        </h1>
        <ul class={styles.multi} aria-hidden="true">
          {titles.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ul>
      </header>
      <div class={styles.grid} role="group" aria-label={t('language.title')}>
        {languages.map((l) => (
          <button
            key={l.code}
            type="button"
            class={`${styles.tile} ${language.value === l.code && l.enabled ? styles.selected : ''}`}
            disabled={!l.enabled}
            aria-disabled={!l.enabled}
            lang={l.code}
            onClick={() => pick(l.code)}
          >
            <span class={styles.name}>{l.name}</span>
            {!l.enabled ? <span class={styles.soon}>{t('language.comingSoon')}</span> : null}
          </button>
        ))}
      </div>
    </main>
  )
}
