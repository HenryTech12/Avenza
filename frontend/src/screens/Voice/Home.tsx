import { useEffect, useRef, useState } from 'preact/hooks'
import { useLocation } from 'preact-iso'
import { Icon, type IconName } from '../../components/Icon/Icon'
import { ListeningOrb } from '../../components/ListeningOrb/ListeningOrb'
import {
  uiState, micLevel, isSpeaking, partialTranscript, hintGrown, conversation, sayLocally, lockTransfers, flags,
} from '../../session/session'
import { fetchBalance, fetchProfile, type Balance } from '../../session/account'
import { formatNaira } from '../../lib/format'
import { t } from '../../i18n'
import styles from './Home.module.css'

function greeting(now = new Date()): string {
  const h = now.getHours()
  return h < 12 ? t('home.morning') : h < 17 ? t('home.afternoon') : t('home.evening')
}

/** Mic-level bars either side of the orb (decorative). */
function Waveform({ flip = false }: { flip?: boolean }) {
  const lvl = isSpeaking.value ? 0.15 : micLevel.value
  const shape = [0.35, 0.6, 0.9, 0.55, 0.8, 0.4, 0.25]
  return (
    <span class={`${styles.wave} ${flip ? styles.flip : ''}`} aria-hidden="true">
      {shape.map((s, i) => (
        <span key={i} style={{ transform: `scaleY(${Math.max(0.12, Math.min(1, s * (0.3 + lvl * 1.6)))})` }} />
      ))}
    </span>
  )
}

/**
 * The home screen from the prototype: greeting, the always-on orb, the conversation so far,
 * the balance and quick actions. Voice is still the main way in; every action here can also be said.
 */
export function Home() {
  const { route } = useLocation()
  const [name, setName] = useState<string | null>(null)
  const [balance, setBalance] = useState<Balance | null>(null)
  const [balanceError, setBalanceError] = useState(false)
  const [showBalance, setShowBalance] = useState(false)
  const statusRef = useRef<HTMLHeadingElement>(null)

  useEffect(() => {
    fetchProfile().then((me) => setName(me.displayName?.split(' ')[0] || null)).catch(() => undefined)
    fetchBalance().then(setBalance).catch(() => setBalanceError(true))
  }, [])

  const ui = uiState.value
  useEffect(() => statusRef.current?.focus({ preventScroll: true }), [ui])
  const status = ui === 'hearing' ? t('status.hearing') : ui === 'checking' ? t('status.checking') : t('status.listening')
  const amount = balance?.availableDisplay ?? (balance?.availableKobo != null ? formatNaira(balance.availableKobo) : null)

  const checkBalance = async () => {
    setShowBalance(true)
    let b = balance
    if (!b) {
      try {
        b = await fetchBalance()
        setBalance(b)
        setBalanceError(false)
      } catch {
        setBalanceError(true)
      }
    }
    const shown = b?.availableDisplay ?? (b?.availableKobo != null ? formatNaira(b.availableKobo) : null)
    sayLocally(shown ? t('home.balanceSaid', { amount: shown }) : t('home.balanceUnavailable'))
  }

  const actions: Array<{ icon: IconName; label: string; run: () => void }> = [
    { icon: 'send', label: t('home.send'), run: () => sayLocally(t('home.sendHint')) },
    { icon: 'wallet', label: t('home.checkBalance'), run: () => void checkBalance() },
    { icon: 'history', label: t('home.history'), run: () => route('/history') },
  ]
  if (flags.emergencyLock) actions.push({ icon: 'lock', label: t('home.lock'), run: () => void lockTransfers() })

  const lines = conversation.value.slice(-3)
  const live = ui === 'hearing' ? partialTranscript.value : ''

  return (
    <div class={styles.home}>
      <section class={styles.hello}>
        <p class={styles.greeting}>
          <span class={styles.greet}>{greeting()}</span>
          <span class={styles.name}>{name ?? t('home.there')}</span>
        </p>
        <p class="muted">{t('home.intro')}</p>
      </section>

      <section class={styles.orbRow} data-panel={ui}>
        <Waveform />
        <ListeningOrb mode={ui === 'hearing' ? 'hearing' : ui === 'checking' ? 'checking' : 'listening'} level={micLevel} speaking={isSpeaking} size={170} />
        <Waveform flip />
      </section>
      {/* The current state is always the page's h1, so screen readers announce it (as on every voice panel). */}
      <div class={styles.status}>
        <span class={styles.dot} aria-hidden="true" />
        <h1 tabIndex={-1} ref={statusRef}>{status}</h1>
        <span class="muted" aria-hidden="true">· {t('home.alwaysOn')}</span>
      </div>
      {hintGrown.value ? <p class={styles.nudge}>{t('hint.noSpeech')}</p> : null}

      {lines.length > 0 || live ? (
        <ol class={styles.chat} aria-label={t('home.conversation')}>
          {lines.map((l) => (
            <li key={l.at} class={l.who === 'you' ? styles.you : styles.avenza}>
              <span class="sr-only">{l.who === 'you' ? t('home.you') : t('home.avenza')}: </span>
              {l.text}
            </li>
          ))}
          {live ? <li class={`${styles.you} ${styles.partial}`}>{live}</li> : null}
        </ol>
      ) : null}

      <section class={styles.balance} aria-label={t('home.balance')}>
        <div class={styles.balanceTop}>
          <span class="muted">{t('home.balance')}</span>
          <button
            type="button"
            class={styles.eye}
            onClick={() => setShowBalance((v) => !v)}
            aria-label={showBalance ? t('home.hideBalance') : t('home.showBalance')}
            aria-pressed={showBalance}
          >
            <Icon name={showBalance ? 'eye-off' : 'eye'} size={20} />
          </button>
        </div>
        <p class={`${styles.amount} tabular`}>
          {balanceError && !amount ? <span class={styles.unavailable}>{t('home.balanceUnavailable')}</span>
            : showBalance && amount ? amount
            : <span aria-label={t('home.balanceHidden')}>₦ ••••••</span>}
        </p>
      </section>

      <section aria-label={t('home.actions')} class={styles.actions}>
        {actions.map((a) => (
          <button key={a.label} type="button" class={styles.action} onClick={a.run}>
            <span class={styles.actionIcon}><Icon name={a.icon} size={22} /></span>
            <span>{a.label}</span>
          </button>
        ))}
      </section>

      <section class={styles.say}>
        <Icon name="wave" size={22} />
        <div>
          <p class="muted">{t('home.youCanSay')}:</p>
          <p>“{t('home.example1')}”</p>
          <p>“{t('home.example2')}”</p>
        </div>
      </section>
    </div>
  )
}
