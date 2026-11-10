import { useEffect, useRef, useState } from 'preact/hooks'
import { useLocation } from 'preact-iso'
import { BigButton } from '../../components/BigButton/BigButton'
import { Icon } from '../../components/Icon/Icon'
import { registerFingerprint, enrolError, deviceToken, type EnrolOutcome } from '../../session/session'
import { t } from '../../i18n'
import styles from './FingerprintSetup.module.css'

const messages: Record<Exclude<EnrolOutcome, 'ok'>, string> = {
  cancelled: 'finger.cancelled',
  'no-authenticator': 'finger.noAuthenticator',
  'already-registered': 'finger.already',
  'name-required': 'finger.nameRequired',
  error: 'finger.error',
}

export function FingerprintSetup() {
  const { route } = useLocation()
  const heading = useRef<HTMLHeadingElement>(null)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(false)
  const [name, setName] = useState('')
  const [problem, setProblem] = useState<Exclude<EnrolOutcome, 'ok'> | null>(null)

  useEffect(() => heading.current?.focus({ preventScroll: true }), [])

  const register = async () => {
    setBusy(true)
    setProblem(null)
    const r = await registerFingerprint(name)
    setBusy(false)
    if (r === 'ok') {
      setDone(true)
      setTimeout(() => route('/', true), 1100)
    } else if (r === 'already-registered') {
      setDone(true)
      setTimeout(() => route('/', true), 600)
    } else {
      setProblem(r)
    }
  }

  return (
    <main class="page">
      <div class="page-center">
        <span class={`${styles.ring} ${done ? styles.done : ''}`}>
          <Icon name={done ? 'check' : 'fingerprint'} size={72} />
        </span>
        <h1 tabIndex={-1} ref={heading}>
          {done ? t('finger.success') : t('finger.title')}
        </h1>
        {!done ? <p class="muted">{t('finger.body')}</p> : null}
        {!done && !deviceToken.value ? (
          <form class={styles.field} onSubmit={(e) => { e.preventDefault(); void register() }}>
            <label for="display-name">{t('finger.nameLabel')}</label>
            <input
              id="display-name"
              class={styles.input}
              type="text"
              autocomplete="name"
              maxLength={200}
              required
              aria-invalid={problem === 'name-required'}
              aria-describedby="display-name-hint"
              value={name}
              onInput={(e) => setName((e.currentTarget as HTMLInputElement).value)}
            />
            <span id="display-name-hint" class="muted">{t('finger.nameHint')}</span>
          </form>
        ) : null}
        {problem ? (
          <p class={styles.problem} role="alert">
            {problem === 'error' && enrolError.value ? enrolError.value : t(messages[problem])}
          </p>
        ) : null}
      </div>
      {!done ? (
        <div class="page-bottom">
          <BigButton onClick={register} loading={busy}>
            {problem === 'cancelled' || problem === 'error' ? t('common.retry') : t('finger.register')}
          </BigButton>
        </div>
      ) : null}
    </main>
  )
}
