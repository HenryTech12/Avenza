import { useEffect, useState } from 'preact/hooks'
import { useLocation } from 'preact-iso'
import { Wordmark } from '../../components/Wordmark/Wordmark'
import { BigButton } from '../../components/BigButton/BigButton'
import { Sheet } from '../../components/Sheet/Sheet'
import { boot, bootProgress, preloadVad, onboardingComplete, unlockAudio } from '../../session/session'
import { registerServiceWorker } from '../../app/pwa'
import { nav } from '../../app/nav'
import { t } from '../../i18n'
import styles from './Boot.module.css'

export function Boot() {
  const { route } = useLocation()
  const [phase, setPhase] = useState<'loading' | 'tap' | 'failed'>('loading')
  const [attempt, setAttempt] = useState(0)

  const proceed = () => {
    preloadVad()
    route(onboardingComplete.value ? (nav.pending ?? '/') : '/onboarding/language', true)
  }

  useEffect(() => {
    let cancelled = false
    registerServiceWorker()
    setPhase('loading')
    boot()
      .then((r) => {
        if (cancelled) return
        if (r.needsTap) setPhase('tap')
        else proceed()
      })
      .catch((e) => {
        console.error('[avenza] boot failed', e)
        if (!cancelled) setPhase('failed')
      })
    return () => {
      cancelled = true
    }
  }, [attempt])

  const start = async () => {
    await unlockAudio()
    proceed()
  }

  if (phase === 'tap') {
    return (
      <button type="button" class={styles.tap} onClick={start} autoFocus>
        <Wordmark size="lg" />
        <span class={styles.tapText}>{t('boot.tap')}</span>
        <span class={styles.tapHint}>{t('boot.tapHint')}</span>
      </button>
    )
  }

  return (
    <main class={`page ${styles.boot}`}>
      <div class="page-center">
        <Wordmark size="lg" />
        <div
          class={styles.bar}
          role="progressbar"
          aria-label={t('boot.loading')}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(bootProgress.value * 100)}
        >
          <span class={styles.fill} style={{ width: `${Math.round(bootProgress.value * 100)}%` }} />
        </div>
      </div>
      {phase === 'failed' ? (
        <Sheet title={t('boot.failed')} icon="warning" tone="danger" message={t('boot.failedBody')}>
          <BigButton onClick={() => setAttempt((a) => a + 1)}>{t('common.retry')}</BigButton>
        </Sheet>
      ) : null}
    </main>
  )
}
