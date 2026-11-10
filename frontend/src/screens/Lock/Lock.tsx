import { useEffect, useRef, useState } from 'preact/hooks'
import { useLocation } from 'preact-iso'
import { Icon } from '../../components/Icon/Icon'
import { BigButton } from '../../components/BigButton/BigButton'
import { unlockTransfers, locked } from '../../session/session'
import { t } from '../../i18n'
import styles from './Lock.module.css'

/** Stub behind the `emergencyLock` flag. Mock unlock only; real unlock needs backend agreement. */
export function Lock() {
  const { route } = useLocation()
  const heading = useRef<HTMLHeadingElement>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => heading.current?.focus({ preventScroll: true }), [])

  const unlock = async () => {
    setBusy(true)
    const ok = await unlockTransfers()
    setBusy(false)
    if (ok) route('/', true)
  }

  return (
    <main class={`page ${styles.lock}`}>
      <div class="page-center">
        <span class={styles.ring}>
          <Icon name="lock" size={64} />
        </span>
        <h1 tabIndex={-1} ref={heading}>{t('lock.title')}</h1>
        <p class="muted">{t('lock.body')}</p>
      </div>
      <div class="page-bottom">
        <BigButton onClick={unlock} loading={busy} variant={locked.value ? 'primary' : 'secondary'}>
          <Icon name="fingerprint" size={22} /> {t('lock.unlock')}
        </BigButton>
      </div>
    </main>
  )
}
