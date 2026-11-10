import { useEffect, useRef, useState } from 'preact/hooks'
import { useLocation } from 'preact-iso'
import { BigButton } from '../../components/BigButton/BigButton'
import { Icon } from '../../components/Icon/Icon'
import { registerFingerprint, enrolError, deviceToken, audioRunning, speakLine, answerLocale, type EnrolOutcome } from '../../session/session'
import { ask, nameFrom, voiceAnswersSupported } from '../../audio/listen'
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

  const [listening, setListening] = useState(false)
  useEffect(() => heading.current?.focus({ preventScroll: true }), [])

  // Voice onboarding: ask for the name, fill it in from the answer, then open the fingerprint prompt.
  // If the browser will only open it after a touch, Avenza says so and the whole screen becomes the target.
  const [needTouch, setNeedTouch] = useState(false)
  useEffect(() => {
    if (!audioRunning.value) return
    if (deviceToken.value) {
      void speakLine(t('onboard.fingerSay')).then(() => register('', true))
      return
    }
    if (!voiceAnswersSupported()) return
    let alive = true
    const stop = ask({
      lang: answerLocale(),
      say: (n) => speakLine(n === 0 ? t('onboard.askName') : t('onboard.noName')),
      onListening: setListening,
      onText: (text) => {
        const heardName = nameFrom(text)
        if (heardName.length < 2) return false
        setName(heardName)
        void speakLine(t('onboard.nameHeard', { name: heardName })).then(() => {
          if (alive) void register(heardName, true)
        })
        return true
      },
    })
    return () => {
      alive = false
      stop()
    }
  }, [audioRunning.value])

  const register = async (who = name, automatic = false) => {
    setBusy(true)
    setProblem(null)
    setNeedTouch(false)
    const r = await registerFingerprint(who)
    setBusy(false)
    if (r === 'ok') {
      setDone(true)
      setTimeout(() => route('/', true), 1100)
    } else if (r === 'already-registered') {
      setDone(true)
      setTimeout(() => route('/', true), 600)
    } else if (automatic && r === 'cancelled') {
      // The browser refused to open the prompt without a touch (or it was dismissed):
      // say what to do, and make the whole screen the place to touch.
      setNeedTouch(true)
      void speakLine(t('onboard.tapToFinger'))
    } else {
      setProblem(r)
      void speakLine(r === 'error' && enrolError.value ? enrolError.value : t(messages[r]))
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
            <span id="display-name-hint" class="muted">{listening ? t('onboard.sayName') : t('finger.nameHint')}</span>
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
          <BigButton onClick={() => void register()} loading={busy}>
            {problem === 'cancelled' || problem === 'error' ? t('common.retry') : t('finger.register')}
          </BigButton>
        </div>
      ) : null}
      {needTouch && !done ? (
        <button type="button" class={styles.touchAnywhere} onClick={() => void register()} aria-label={t('onboard.tapToFingerLabel')}>
          <span>{t('onboard.tapToFinger')}</span>
        </button>
      ) : null}
    </main>
  )
}
