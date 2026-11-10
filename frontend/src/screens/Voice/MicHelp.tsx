import { useState } from 'preact/hooks'
import { StatusPanel } from '../../components/StatusPanel/StatusPanel'
import { BigButton } from '../../components/BigButton/BigButton'
import { startVoice } from '../../session/session'
import { t } from '../../i18n'
import styles from './Voice.module.css'

/** Shown when the microphone permission is denied. */
export function MicHelp({ onRetry }: { onRetry: () => Promise<boolean> }) {
  const [busy, setBusy] = useState(false)
  const retry = async () => {
    setBusy(true)
    const ok = await onRetry()
    setBusy(false)
    if (ok) void startVoice()
  }
  return (
    <>
      <section class={styles.center}>
        <StatusPanel icon="mic" tone="warning" status={t('mic.title')} line={t('error.mic_denied')} />
        <ol class={styles.steps}>
          <li>{t('mic.step1')}</li>
          <li>{t('mic.step2')}</li>
          <li>{t('mic.step3')}</li>
        </ol>
      </section>
      <div class="page-bottom">
        <BigButton onClick={retry} loading={busy}>
          {t('common.retry')}
        </BigButton>
      </div>
    </>
  )
}
