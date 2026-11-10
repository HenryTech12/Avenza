import { useEffect } from 'preact/hooks'
import { Link } from './Link'
import { Icon } from '../../components/Icon/Icon'
import { Wordmark } from '../../components/Wordmark/Wordmark'
import { SimulatedBadge } from '../../components/SimulatedBadge/SimulatedBadge'
import { TranscriptLine } from '../../components/TranscriptLine/TranscriptLine'
import { Sheet } from '../../components/Sheet/Sheet'
import { BigButton } from '../../components/BigButton/BigButton'
import {
  uiState, errorOverlay, connection, simulated, transcript, partialTranscript, flags, startVoice, stopVoice,
  showLatency, lastLatency, lockTransfers, dismissError, retryConnection, duplicateNotice, dismissDuplicate,
  retryMic, unclearReply,
} from '../../session/session'
import { Panels } from './Panels'
import { MicHelp } from './MicHelp'
import { t } from '../../i18n'
import styles from './Voice.module.css'

function ConnectionDot() {
  const c = connection.value
  if (c === 'open') return null
  const label = c === 'connecting' ? t('boot.loading') : c === 'reconnecting' ? t('voice.reconnecting') : t('voice.offline')
  return (
    <span class={styles.conn} role="status">
      <span class={styles.connDot} aria-hidden="true" />
      {label}
    </span>
  )
}

export function Voice() {
  useEffect(() => {
    void startVoice()
    return () => stopVoice()
  }, [])

  const err = errorOverlay.value
  const ui = uiState.value
  const showTranscript = flags.showTranscript && (ui === 'listening' || ui === 'hearing' || ui === 'checking' || ui === 'readback')
  const live = ui === 'hearing' ? partialTranscript.value : transcript.value
  const micDenied = err?.code === 'mic_denied'

  return (
    <main class={`page ${styles.voice}`}>
      <header class={styles.top}>
        <Link href="/settings" class={styles.iconBtn} aria-label={t('common.settings')}>
          <Icon name="settings" />
        </Link>
        <Wordmark size="sm" />
        <div class={styles.right}>
          <ConnectionDot />
          {simulated.value ? <SimulatedBadge /> : null}
        </div>
      </header>

      {showLatency.value && lastLatency.value.endToFirstSoundMs != null ? (
        <p class={styles.latency} data-testid="latency">
          {t('voice.latency', { ms: lastLatency.value.endToFirstSoundMs })}
        </p>
      ) : null}

      {micDenied ? (
        <MicHelp onRetry={retryMic} />
      ) : (
        <>
          <Panels />
          <div class={styles.transcript}>
            {showTranscript ? <TranscriptLine text={live} partial={ui === 'hearing'} /> : null}
            {unclearReply.value && ui === 'readback' ? <p class={styles.unclear}>{t('hint.unclear')}</p> : null}
          </div>
        </>
      )}

      {flags.emergencyLock && !micDenied ? (
        <button type="button" class={styles.lock} onClick={lockTransfers}>
          <Icon name="lock" size={18} />
          {t('voice.lock')}
        </button>
      ) : null}

      {err && !micDenied ? <ErrorSheet code={err.code} /> : null}
      {duplicateNotice.value ? (
        <Sheet
          title={t('duplicate.title')}
          icon="warning"
          tone="warning"
          message={t('duplicate.body', duplicateNotice.value)}
          onClose={dismissDuplicate}
        >
          <BigButton variant="secondary" onClick={dismissDuplicate}>{t('duplicate.yes')}</BigButton>
          <BigButton variant="danger" onClick={dismissDuplicate}>{t('duplicate.no')}</BigButton>
        </Sheet>
      ) : null}
    </main>
  )
}

function ErrorSheet({ code }: { code: string }) {
  const message = t(`error.${code}`) === `error.${code}` ? t('error.generic') : t(`error.${code}`)
  const waiting = code === 'connection_lost'
  return (
    <Sheet
      title={waiting ? t('voice.reconnecting') : t('error.title')}
      icon={code === 'offline' || waiting ? 'wifi-off' : 'warning'}
      tone="danger"
      message={message}
      onClose={waiting ? undefined : dismissError}
    >
      {code === 'offline' ? <BigButton onClick={retryConnection}>{t('common.retry')}</BigButton> : null}
      {!waiting && code !== 'offline' ? <BigButton onClick={dismissError}>{t('common.close')}</BigButton> : null}
    </Sheet>
  )
}
