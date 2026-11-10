import { useEffect, useRef, useState } from 'preact/hooks'
import { useLocation } from 'preact-iso'
import { Icon } from '../../components/Icon/Icon'
import { Wordmark } from '../../components/Wordmark/Wordmark'
import {
  audioRunning, speakLine, appLine, chooseLanguage, giveConsent, registerFingerprint, enrolError, languages,
  type EnrolOutcome,
} from '../../session/session'
import { ask, isAgreement, languageFrom, nameFrom, voiceAnswersSupported } from '../../audio/listen'
import { speechProviders } from '../../config/languages'
import type { Lang } from '../../protocol/messages'
import { t } from '../../i18n'
import styles from './Onboarding.module.css'

type Step = 'name' | 'language' | 'consent' | 'finger' | 'done'
type Line = { who: 'avenza' | 'you'; text: string; id: number }
// Language first (team decision, 10 Nov): every question after it is in the chosen language.
const STEPS: Exclude<Step, 'done'>[] = ['language', 'name', 'consent', 'finger']

const problems: Record<Exclude<EnrolOutcome, 'ok'>, string> = {
  cancelled: 'onboard.tapToFinger',
  'no-authenticator': 'finger.noAuthenticator',
  'already-registered': 'finger.already',
  'name-required': 'ob.askNameAgain',
  error: 'finger.error',
}

/**
 * Onboarding as a short conversation: greeting, name, language, a one-sentence consent, fingerprint.
 * Avenza asks every question out loud and listens for the answer; nothing has to be found or typed.
 * Each step also has a small control for people who prefer to tap or type.
 */
export function Onboarding() {
  const { route } = useLocation()
  const [step, setStep] = useState<Step>('language')
  const [lines, setLines] = useState<Line[]>([])
  const [speaking, setSpeaking] = useState(false)
  const [listening, setListening] = useState(false)
  const [typed, setTyped] = useState('')
  const [busy, setBusy] = useState(false)
  const [needTouch, setNeedTouch] = useState(false)
  const nameRef = useRef('')
  const nextId = useRef(0)
  const chatEnd = useRef<HTMLLIElement>(null)
  const voice = voiceAnswersSupported()

  // A repeated question is spoken again but not shown twice.
  const push = (who: Line['who'], text: string) =>
    setLines((l) => (l.length && l[l.length - 1].who === who && l[l.length - 1].text === text ? l : [...l, { who, text, id: nextId.current++ }]))
  const say = async (text: string) => {
    push('avenza', text)
    setSpeaking(true)
    await speakLine(text)
    setSpeaking(false)
  }
  // A fixed line in the chosen language, voiced by the server (the phone rarely speaks Yoruba/Hausa/Igbo).
  const sayLine = async (id: string, fallbackKey: string) => {
    const line = await appLine(id, t(fallbackKey))
    push('avenza', line.text)
    setSpeaking(true)
    await line.play()
    setSpeaking(false)
    return line.text
  }
  const [touchText, setTouchText] = useState('')

  useEffect(() => chatEnd.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }), [lines.length])

  /* ---------------------------------------------------------------- answers (voice or tap) */
  const answerName = (raw: string) => {
    const n = nameFrom(raw)
    if (n.length < 2 || step !== 'name') return false
    nameRef.current = n
    push('you', n)
    setTyped('')
    setStep('consent')
    return true
  }
  const answerLanguage = async (code: Lang, said?: string) => {
    if (step !== 'language') return
    push('you', said ?? languages.find((l) => l.code === code)?.name ?? code)
    await chooseLanguage(code)
    await sayLine('ob_language_set', 'ob.languageSet') // first line in the new language
    setStep('name')
  }
  const answerConsent = async (said?: string) => {
    if (step !== 'consent' || busy) return
    push('you', said ?? t('ob.agree'))
    setBusy(true)
    const r = await giveConsent()
    setBusy(false)
    if (r === 'ok') setStep('finger')
    else void (r === 'mic-denied' ? sayLine('ob_mic_denied', 'ob.micDenied') : sayLine('ob_save_failed', 'ob.saveFailed'))
  }
  const register = async () => {
    setBusy(true)
    setNeedTouch(false)
    const r = await registerFingerprint(nameRef.current, { quiet: true })
    setBusy(false)
    if (r === 'ok' || r === 'already-registered') {
      setStep('done')
      return
    }
    if (r === 'cancelled') {
      // the browser wants a touch first, or the prompt was dismissed: the whole screen is the target
      setNeedTouch(true)
      setTouchText(await sayLine('ob_finger_again', 'onboard.tapToFinger'))
      return
    }
    void say(r === 'error' && enrolError.value ? enrolError.value : t(problems[r]))
  }

  /* ---------------------------------------------------------------- the conversation */
  useEffect(() => {
    if (!audioRunning.value && step !== 'done') return
    let stop: () => void = () => undefined
    let alive = true
    const listen = (opts: Parameters<typeof ask>[0]) => {
      if (voice) stop = ask({ ...opts, onListening: setListening })
      else void opts.say(0)
    }
    switch (step) {
      case 'language':
        listen({
          lang: 'en-NG',
          say: (n) => (n === 0 ? sayLine('ob_ask_language', 'ob.askLanguage') : sayLine('ob_ask_language_again', 'ob.askLanguageAgain')).then(() => undefined),
          onText: (text) => {
            const code = languageFrom(text)
            if (!code) return false
            void answerLanguage(code, text)
            return true
          },
        })
        break
      case 'name':
        listen({
          lang: 'en-NG',
          say: async (n) => {
            if (n === 0) await sayLine('ob_greeting', 'ob.greeting')
            await (n === 0 ? sayLine('ob_ask_name', 'ob.askName') : sayLine('ob_ask_name_again', 'ob.askNameAgain'))
          },
          onText: answerName,
        })
        break
      case 'consent':
        listen({
          // Nigerian English recognition hears "I agree" and the Yoruba/Hausa/Igbo answers best;
          // a Yoruba recogniser (where one exists) missed an English "I agree" (phone test, 10 Nov).
          lang: 'en-NG',
          say: (n) => (n === 0 ? sayLine('ob_consent', 'ob.consent') : sayLine('ob_consent_again', 'ob.consentAgain')).then(() => undefined),
          onText: (text) => {
            if (!isAgreement(text)) return false
            void answerConsent(text)
            return true
          },
        })
        break
      case 'finger':
        // Chrome on Android opens the fingerprint prompt only right after a touch (a browser security
        // rule). So Avenza says "touch the screen anywhere" and the whole screen becomes the target;
        // where the browser allows it without a touch, the prompt opens straight away.
        void sayLine('ob_finger', 'ob.finger').then((text) => {
          if (!alive) return
          const activation = (navigator as Navigator & { userActivation?: { isActive: boolean } }).userActivation
          if (activation && !activation.isActive && !navigator.webdriver) {
            setTouchText(text)
            setNeedTouch(true)
          } else void register()
        })
        break
      case 'done':
        void sayLine('ob_done', 'ob.done').then(() => {
          if (alive) route('/', true)
        })
        break
    }
    return () => {
      alive = false
      stop()
      setListening(false)
    }
  }, [step, audioRunning.value])

  const index = step === 'done' ? STEPS.length : STEPS.indexOf(step)

  return (
    <main class={styles.page}>
      <header class={styles.head}>
        <Wordmark size="sm" />
        <h1 class="sr-only">{t('ob.title')}</h1>
        <ol class={styles.steps} aria-label={t('ob.progress', { n: Math.min(index + 1, 4) })}>
          {STEPS.map((s, i) => (
            <li key={s} class={i < index ? styles.stepDone : i === index ? styles.stepNow : ''} aria-current={i === index ? 'step' : undefined}>
              <span class={styles.stepDot} aria-hidden="true">{i < index ? <Icon name="check" size={12} /> : i + 1}</span>
              <span class={styles.stepLabel}>{t(`ob.step.${s}`)}</span>
            </li>
          ))}
        </ol>
      </header>

      <section class={styles.stage} aria-hidden="true">
        <div class={`${styles.orb} ${speaking ? styles.orbSpeaking : ''} ${listening ? styles.orbListening : ''}`}>
          <span class={styles.ring} />
          <span class={styles.ring} />
          <span class={styles.pearl}><span class={styles.shine} /></span>
        </div>
        <p class={styles.state}>
          {speaking ? t('ob.speaking') : listening ? t('ob.listening') : ' '}
          {speaking || listening ? <span class={styles.bars}><i /><i /><i /><i /></span> : null}
        </p>
      </section>

      <ol class={styles.chat} aria-live="polite" tabIndex={0} aria-label={t('home.conversation')}>
        {lines.map((l) => (
          <li key={l.id} class={l.who === 'you' ? styles.you : styles.avenza}>{l.text}</li>
        ))}
        <li ref={chatEnd} class={styles.anchor} aria-hidden="true" />
      </ol>

      <section class={styles.controls} aria-label={t('ob.or')}>
        {step === 'name' ? (
          <form class={styles.row} onSubmit={(e) => { e.preventDefault(); answerName(typed) }}>
            <label class="sr-only" for="ob-name">{t('ob.typeName')}</label>
            <input id="ob-name" class={styles.input} autocomplete="name" placeholder={t('ob.typeName')} value={typed}
              onInput={(e) => setTyped((e.currentTarget as HTMLInputElement).value)} />
            <button type="submit" class={styles.primary}>{t('ob.continue')}</button>
          </form>
        ) : step === 'language' ? (
          <div class={styles.chips} role="group" aria-label={t('language.title')}>
            {languages.map((l) => (
              <button key={l.code} type="button" class={styles.chip} lang={l.code} onClick={() => void answerLanguage(l.code)}>
                {l.name}{l.beta ? <span class={styles.beta}>Beta</span> : null}
              </button>
            ))}
          </div>
        ) : step === 'consent' ? (
          <div class={styles.col}>
            <button type="button" class={styles.primary} onClick={() => void answerConsent()} disabled={busy}>{t('ob.agree')}</button>
            <details class={styles.details}>
              <summary>{t('ob.details')}</summary>
              <p>{t('consent.p2', { providers: speechProviders.join(', ') })}</p>
              <p>{t('consent.p3')}</p>
              <p>{t('consent.p5')}</p>
            </details>
          </div>
        ) : step === 'finger' ? (
          <button type="button" class={styles.primary} onClick={() => void register()} disabled={busy}>
            <Icon name="fingerprint" size={20} /> {t('ob.register')}
          </button>
        ) : null}
      </section>

      {needTouch && step === 'finger' ? (
        <button type="button" class={styles.touchAnywhere} onClick={() => void register()} aria-label={t('onboard.tapToFingerLabel')}>
          <span><Icon name="fingerprint" size={28} /> {touchText || t('onboard.tapToFinger')}</span>
        </button>
      ) : null}
    </main>
  )
}
