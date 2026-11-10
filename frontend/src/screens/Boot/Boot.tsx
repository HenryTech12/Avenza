import { useEffect, useRef, useState } from 'preact/hooks'
import { useLocation } from 'preact-iso'
import { BigButton } from '../../components/BigButton/BigButton'
import { Sheet } from '../../components/Sheet/Sheet'
import { boot, bootProgress, preloadVad, onboardingComplete, unlockAudio, tryStartSoundWithoutTouch } from '../../session/session'
import { registerServiceWorker } from '../../app/pwa'
import { nav } from '../../app/nav'
import { timeouts } from '../../config/timeouts'
import { t } from '../../i18n'
import styles from './Boot.module.css'

// Slow-rising light particles over the water (fixed positions so every load looks the same).
const PARTICLES = [
  { x: 12, y: 62, d: 0, t: 9 }, { x: 24, y: 70, d: 2.1, t: 11 }, { x: 37, y: 58, d: 4.3, t: 10 },
  { x: 49, y: 74, d: 1.2, t: 12 }, { x: 61, y: 60, d: 3.4, t: 9.5 }, { x: 72, y: 68, d: 0.7, t: 10.5 },
  { x: 84, y: 63, d: 2.8, t: 11.5 }, { x: 90, y: 72, d: 5, t: 9 }, { x: 6, y: 76, d: 3.9, t: 12.5 },
  { x: 55, y: 66, d: 6, t: 10 },
]

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
    route(onboardingComplete.value ? (nav.pending ?? '/') : '/onboarding', true)
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
        const running = !r.needsTap || (await tryStartSoundWithoutTouch())
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

  const ready = bootProgress.value >= 1
  const splash = (
    <>
      <div class={styles.sky} aria-hidden="true">
        <span class={styles.sun} />
        <span class={styles.water} />
        {PARTICLES.map((p, i) => (
          <span key={i} class={styles.particle} style={{ left: `${p.x}%`, top: `${p.y}%`, animationDelay: `${p.d}s`, animationDuration: `${p.t}s` }} />
        ))}
      </div>
      <div class={styles.top}>
        <span class={styles.word} role="img" aria-label="Avenza">
          {'AVENZA'.split('').map((ch, i) => (
            <span key={i} aria-hidden="true" style={{ animationDelay: `${0.15 + i * 0.08}s` }}>{ch}</span>
          ))}
        </span>
        <p class={styles.tagline}>{t('splash.tagline')}</p>
      </div>
      <div class={styles.stage} aria-hidden="true">
        <span class={styles.ripple} />
        <span class={styles.ripple} style={{ animationDelay: '1.3s' }} />
        <span class={styles.ripple} style={{ animationDelay: '2.6s' }} />
        <div class={styles.pearl}>
          <span class={styles.shine} />
        </div>
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
            <p class={styles.claim}>{t('splash.foot1')}</p>
            <p class={styles.claim2}>{t('splash.foot2')}</p>
            <p class={styles.status}>
              {ready ? t('splash.ready') : t('splash.preparing')}
              <span class={styles.dots} aria-hidden="true"><i>.</i><i>.</i><i>.</i></span>
            </p>
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
