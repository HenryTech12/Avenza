import { useEffect, useRef, useState } from 'preact/hooks'
import { useLocation } from 'preact-iso'
import { languages, chooseLanguage, language, audioRunning, speakLine } from '../../session/session'
import { listenFor, languageFrom, voiceAnswersSupported } from '../../audio/listen'
import { Icon } from '../../components/Icon/Icon'
import { t } from '../../i18n'
import type { Lang } from '../../protocol/messages'
import styles from './Language.module.css'

const titles = ['Choose your language', 'Yan èdè rẹ', 'Zaɓi harshenka', 'Họrọ asụsụ gị']

export function Language() {
  const { route } = useLocation()
  const heading = useRef<HTMLHeadingElement>(null)
  const [listening, setListening] = useState(false)
  const picked = useRef(false)
  useEffect(() => heading.current?.focus({ preventScroll: true }), [])

  const pick = async (code: Lang) => {
    if (picked.current) return
    picked.current = true
    await chooseLanguage(code)
    route('/onboarding/consent')
  }

  // Onboarding by voice: Avenza asks, the customer says the language. Tapping a tile still works.
  useEffect(() => {
    if (!audioRunning.value || !voiceAnswersSupported()) return
    let alive = true
    let stop = () => undefined as void
    void speakLine(t('onboard.askLanguage')).then(() => {
      if (!alive) return
      setListening(true)
      stop = listenFor('en-NG', (text) => {
        const code = languageFrom(text)
        if (!code) return false
        void pick(code)
        return true
      })
    })
    return () => {
      alive = false
      stop()
    }
  }, [audioRunning.value])

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
            {!l.enabled ? <span class={styles.soon}>{t('language.comingSoon')}</span> : l.beta ? <span class={styles.soon}>Beta</span> : null}
          </button>
        ))}
      </div>
      {listening ? (
        <p class={styles.voiceHint} aria-live="polite">
          <Icon name="wave" size={18} /> {t('onboard.sayLanguage')}
        </p>
      ) : null}
    </main>
  )
}
