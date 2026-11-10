import { useEffect, useRef, useState } from 'preact/hooks'
import { useLocation } from 'preact-iso'
import { BigButton } from '../../components/BigButton/BigButton'
import { Sheet } from '../../components/Sheet/Sheet'
import { Icon } from '../../components/Icon/Icon'
import { audioRunning, giveConsent, speakConsent, stopSpeaking, speakLine, answerLocale } from '../../session/session'
import { listenFor, isAgreement, voiceAnswersSupported } from '../../audio/listen'
import { speechProviders } from '../../config/languages'
import { t } from '../../i18n'
import styles from './Consent.module.css'

export function Consent() {
  const { route } = useLocation()
  const heading = useRef<HTMLHeadingElement>(null)
  const [busy, setBusy] = useState(false)
  const [notNow, setNotNow] = useState(false)
  const [problem, setProblem] = useState<'mic' | 'save' | null>(null)
  const [listening, setListening] = useState(false)
  const [heard, setHeard] = useState('')
  const busyRef = useRef(false)

  useEffect(() => heading.current?.focus({ preventScroll: true }), [])

  // Read the consent aloud as soon as sound is available (audio unlocks on the first tap),
  // then listen for "I agree". The button does the same thing.
  useEffect(() => {
    let spoke = false
    let stopListening = () => undefined as void
    const listen = () => {
      if (!voiceAnswersSupported()) return
      setListening(true)
      stopListening = listenFor(answerLocale(), (text) => {
        if (!isAgreement(text) || busyRef.current) return false
        void agree()
        return true
      }, setHeard)
    }
    const speak = () => {
      if (spoke || !audioRunning.value) return
      spoke = true
      setTimeout(async () => {
        await speakConsent()
        await speakLine(t('onboard.sayAgree'))
        listen()
      }, 300)
    }
    speak()
    const first = () => {
      // the first tap anywhere unlocks audio on browsers that need a gesture
      setTimeout(speak, 50)
    }
    document.addEventListener('pointerdown', first, { once: true })
    return () => {
      document.removeEventListener('pointerdown', first)
      stopListening()
      setListening(false)
      stopSpeaking()
    }
  }, [audioRunning.value])

  const agree = async () => {
    if (busyRef.current) return
    busyRef.current = true
    setBusy(true)
    setProblem(null)
    const r = await giveConsent()
    setBusy(false)
    busyRef.current = false
    if (r === 'ok') route('/onboarding/fingerprint')
    else setProblem(r === 'mic-denied' ? 'mic' : 'save')
  }

  return (
    <main class="page">
      <h1 tabIndex={-1} ref={heading} class={styles.title}>
        {t('consent.title')}
      </h1>
      <div class={styles.body}>
        <p class={styles.lead}>{t('consent.p1')}</p>
        <ul class={styles.list}>
          <li>
            <Icon name="mic" size={20} />
            <span>{t('consent.p2', { providers: speechProviders.join(', ') })}</span>
          </li>
          <li>
            <Icon name="clock" size={20} />
            <span>{t('consent.p3')}</span>
          </li>
          <li>
            <Icon name="fingerprint" size={20} />
            <span>{t('consent.p4')}</span>
          </li>
          <li>
            <Icon name="settings" size={20} />
            <span>{t('consent.p5')}</span>
          </li>
        </ul>
        <button type="button" class="text-button" onClick={speakConsent}>
          {t('consent.readAgain')}
        </button>
      </div>
      {listening ? (
        <p class={styles.voiceHint} aria-live="polite">
          <Icon name="wave" size={18} /> {heard ? t('onboard.heard', { text: heard }) : t('onboard.sayAgree')}
        </p>
      ) : null}
      {problem ? (
        <p class={styles.problem} role="alert">
          {problem === 'mic' ? t('error.mic_denied') : t('consent.error')}
        </p>
      ) : null}
      <div class="page-bottom">
        <BigButton onClick={agree} loading={busy}>
          {t('consent.agree')}
        </BigButton>
        <button type="button" class="text-button" onClick={() => setNotNow(true)}>
          {t('consent.notNow')}
        </button>
      </div>
      {notNow ? (
        <Sheet title={t('consent.notNowTitle')} icon="lock" message={t('consent.notNowBody')} onClose={() => setNotNow(false)}>
          <BigButton onClick={() => setNotNow(false)}>{t('common.close')}</BigButton>
        </Sheet>
      ) : null}
    </main>
  )
}
