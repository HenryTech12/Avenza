import { useEffect, useRef, useState } from 'preact/hooks'
import { useLocation } from 'preact-iso'
import { Wordmark } from '../../components/Wordmark/Wordmark'
import { BigButton } from '../../components/BigButton/BigButton'
import { Sheet } from '../../components/Sheet/Sheet'
import { boot, bootProgress, preloadVad, onboardingComplete, unlockAudio } from '../../session/session'
import { registerServiceWorker } from '../../app/pwa'
import { nav } from '../../app/nav'
import { timeouts } from '../../config/timeouts'
import { t } from '../../i18n'
import styles from './Boot.module.css'

const wait = (ms: number) => new Promise((r) => setTimeout(r, Math.max(0, ms)))

/**
 * The opening screen from the prototype. It stays for about five seconds while Avenza loads,
 * then Avenza starts talking: onboarding by voice for a new customer, the voice home for everyone else.
 *
 * Browsers only allow sound after one touch, unless Avenza is installed on the home screen
 * (or the browser already trusts the site). When sound is blocked the whole screen becomes one
 * button, and screen readers announce "touch anywhere": a blind customer never has to find a control.
 */
export function Boot() {
  const { route } = useLocation()
  const [phase, setPhase] = useState<'loading' | 'tap' | 'failed'>('loading')
  const [attempt, setAttempt] = useState(0)
  const tapRef = useRef<HTMLButtonElement>(null)

  const proceed = () => {
    preloadVad()
    route(onboardingComplete.value ? (nav.pending ?? '/') : '/onboarding/language', true)
  }

  useEffect(() => {
    let cancelled = false
    const started = Date.now()
    registerServiceWorker()
    setPhase('loading')
    boot()
      .then(async (r) => {
        await wait(timeouts.splashMs - (Date.now() - started))
        if (cancelled) return
        // Try to turn sound on without a touch (installed app, or a site the browser trusts).
        const running = !r.needsTap || (await unlockAudio())
        if (cancelled) return
        if (running) proceed()
        else setPhase('tap')
      })
      .catch((e) => {
        console.error('[avenza] boot failed', e)
        if (!cancelled) setPhase('failed')
      })
    return () => {
      cancelled = true
    }
  }, [attempt])

  useEffect(() => {
    if (phase === 'tap') tapRef.current?.focus()
  }, [phase])

  const start = async () => {
    await unlockAudio()
    proceed()
  }

  const splash = (
    <>
      <div class={styles.sky} aria-hidden="true" />
      <div class={styles.top}>
        <Wordmark size="lg" />
        <p class={styles.tagline}>{t('splash.tagline')}</p>
      </div>
      <div class={styles.pearl} aria-hidden="true">
        <span class={styles.reflection} />
      </div>
      <div class={styles.foot}>
        {phase === 'tap' ? (
          <>
            <span class={styles.tapText}>{t('boot.tap')}</span>
            <span class={styles.tapHint}>{t('boot.tapHint')}</span>
          </>
        ) : (
          <>
            <p>{t('splash.foot1')}</p>
            <p>{t('splash.foot2')}</p>
          </>
        )}
        <span
          class={styles.bar}
          role="progressbar"
          aria-label={t('boot.loading')}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(bootProgress.value * 100)}
        >
          <span class={styles.fill} style={{ width: `${Math.round(bootProgress.value * 100)}%` }} />
        </span>
      </div>
    </>
  )

  if (phase === 'tap') {
    return (
      <button type="button" ref={tapRef} class={styles.splash} onClick={start} aria-label={t('boot.tapLabel')}>
        {splash}
        <span class="sr-only" aria-live="assertive">{t('boot.tapLabel')}</span>
      </button>
    )
  }

  return (
    <main class={styles.splash}>
      <h1 class="sr-only">Avenza</h1>
      {splash}
      {phase === 'failed' ? (
        <Sheet title={t('boot.failed')} icon="warning" tone="danger" message={t('boot.failedBody')}>
          <BigButton onClick={() => setAttempt((a) => a + 1)}>{t('common.retry')}</BigButton>
        </Sheet>
      ) : null}
    </main>
  )
}
