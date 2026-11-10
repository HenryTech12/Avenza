import { useRef } from 'preact/hooks'
import { Icon } from '../../components/Icon/Icon'
import { StatusPanel } from '../../components/StatusPanel/StatusPanel'
import { ListeningOrb } from '../../components/ListeningOrb/ListeningOrb'
import { AmountDisplay } from '../../components/AmountDisplay/AmountDisplay'
import { RecipientCard } from '../../components/RecipientCard/RecipientCard'
import { BigButton } from '../../components/BigButton/BigButton'
import { CountdownRing } from '../../components/CountdownRing/CountdownRing'
import {
  uiState, draft, resultKind, cancelKind, micLevel, isSpeaking, hintGrown, flags, confirm, cancel, retryFingerprint,
  fingerprintRetry, fingerprintDeadline, dismissResult, shareReceipt, copyReference, scamPauseActive, scamPauseUntil,
  unclearReply, readbackWarnings,
} from '../../session/session'
import { timeouts } from '../../config/timeouts'
import { formatNaira, formatTime } from '../../lib/format'
import { t } from '../../i18n'
import styles from './Voice.module.css'

/** The centre of the Voice screen: one panel per client state. */
export function Panels() {
  switch (uiState.value) {
    case 'listening':
      return <ListeningPanel />
    case 'hearing':
      return <HearingPanel />
    case 'checking':
      return <CheckingPanel />
    case 'readback':
      return scamPauseActive.value ? <ScamPausePanel /> : <ReadbackPanel />
    case 'fingerprint':
      return <FingerprintPanel />
    case 'sending':
      return <SendingPanel />
    case 'result':
      return <ResultPanel />
    case 'cancelled':
      return <CancelledPanel />
  }
}

function ListeningPanel() {
  const grown = hintGrown.value
  return (
    <section class={styles.center} data-panel="listening">
      <ListeningOrb mode="listening" level={micLevel} speaking={isSpeaking} />
      <StatusPanel status={t('status.listening')} line={null} />
      <p class={`${styles.hint} ${grown ? styles.hintGrown : ''}`}>{grown ? t('hint.noSpeech') : t('hint.listening')}</p>
    </section>
  )
}

function HearingPanel() {
  return (
    <section class={styles.center} data-panel="hearing">
      <ListeningOrb mode="hearing" level={micLevel} speaking={isSpeaking} />
      <StatusPanel status={t('status.hearing')} line={t('hint.hearing')} />
    </section>
  )
}

function CheckingPanel() {
  return (
    <section class={styles.center} data-panel="checking">
      <ListeningOrb mode="checking" level={micLevel} speaking={isSpeaking} />
      <StatusPanel status={t('status.checking')} line={t('hint.checking')} />
    </section>
  )
}

function ReadbackPanel() {
  const d = draft.value
  return (
    <>
      <section class={styles.center} data-panel="readback">
        <StatusPanel status={t('status.readback')} line={unclearReply.value ? t('hint.unclear') : t('hint.readback')} />
        {d ? (
          <>
            <AmountDisplay amountKobo={d.amountKobo} />
            <RecipientCard name={d.recipientName} bankName={d.bankName} accountMasked={d.accountMasked} isNewRecipient={d.isNewRecipient} />
            {readbackWarnings.value.length > 0 ? (
              <ul class={styles.warnings} aria-label={t('scam.title')}>
                {readbackWarnings.value.map((w) => (
                  <li key={w}>
                    <Icon name="warning" size={18} /> {t(`warn.${w}`) === `warn.${w}` ? w.replaceAll('_', ' ') : t(`warn.${w}`)}
                  </li>
                ))}
              </ul>
            ) : null}
          </>
        ) : null}
      </section>
      {flags.confirmButtons ? (
        <div class="page-bottom">
          <BigButton onClick={() => confirm('yes')}>{t('voice.yes')}</BigButton>
          <BigButton variant="secondary" onClick={() => confirm('repeat')}>
            {t('voice.repeat')}
          </BigButton>
          <BigButton variant="danger" onClick={() => confirm('no')}>
            {t('voice.no')}
          </BigButton>
        </div>
      ) : null}
    </>
  )
}

function ScamPausePanel() {
  const d = draft.value
  return (
    <>
      <section class={styles.center} data-panel="scam-pause">
        <StatusPanel icon="warning" tone="warning" status={t('scam.title')} line={t('scam.body')} />
        {d ? <AmountDisplay amountKobo={d.amountKobo} compact /> : null}
        <CountdownRing deadline={scamPauseUntil.value} totalMs={10_000} tone="warning" />
      </section>
      <div class="page-bottom">
        <BigButton variant="danger" onClick={() => confirm('no')}>
          {t('scam.cancel')}
        </BigButton>
      </div>
    </>
  )
}

function FingerprintPanel() {
  const d = draft.value
  const retry = fingerprintRetry.value
  return (
    <>
      <section class={styles.center} data-panel="fingerprint">
        <span class={styles.fpIcon}>
          <Icon name="fingerprint" size={72} />
        </span>
        <StatusPanel status={t('status.fingerprint')} line={d ? t('voice.summary', { amount: formatNaira(d.amountKobo), name: d.recipientName }) : t('hint.fingerprint')} />
        <CountdownRing deadline={fingerprintDeadline.value} totalMs={timeouts.fingerprintMs} />
        <p class="muted">{t('hint.fingerprint')}</p>
      </section>
      <div class="page-bottom">
        {retry ? <BigButton onClick={retryFingerprint}>{t('voice.tryAgain')}</BigButton> : null}
        <BigButton variant="secondary" onClick={cancel}>
          {t('voice.cancel')}
        </BigButton>
      </div>
    </>
  )
}

function SendingPanel() {
  return (
    <section class={styles.center} data-panel="sending">
      <span class={styles.spinner} aria-hidden="true" />
      <StatusPanel icon="bank" tone="accent" status={t('status.sending')} line={t('hint.sending')} />
    </section>
  )
}

function ResultPanel() {
  const kind = resultKind.value
  const d = draft.value
  const when = useRef(new Date())
  if (kind === 'settled' && d) {
    return (
      <>
        <section class={styles.center} data-panel="settled">
          <StatusPanel icon="check" tone="success" status={t('status.settled')} line={null} />
          <AmountDisplay amountKobo={d.amountKobo} />
          <dl class={styles.receipt}>
            <div><dt>{t('voice.resultTo')}</dt><dd>{d.recipientName}</dd></div>
            <div><dt>{t('voice.resultBank')}</dt><dd class="tabular">{d.bankName} · {d.accountMasked}</dd></div>
            {d.reference ? (
              <div>
                <dt>{t('voice.resultRef')}</dt>
                <dd class={`tabular ${styles.ref}`}>
                  {d.reference}
                  <button type="button" class={styles.copy} onClick={copyReference} aria-label={`${t('common.copy')} ${t('voice.resultRef')}`}>
                    <Icon name="copy" size={18} />
                  </button>
                </dd>
              </div>
            ) : null}
            <div><dt>{t('voice.resultTime')}</dt><dd>{formatTime(when.current)}</dd></div>
          </dl>
        </section>
        <div class="page-bottom">
          <BigButton variant="secondary" onClick={() => void shareReceipt()}>
            <Icon name="share" size={20} /> {t('voice.share')}
          </BigButton>
          <BigButton onClick={dismissResult}>{t('voice.done')}</BigButton>
        </div>
      </>
    )
  }
  if (kind === 'failed') {
    return (
      <>
        <section class={styles.center} data-panel="failed">
          <StatusPanel icon="cross" tone="danger" status={t('status.failed')} line={d?.failureReason ? t('voice.reason', { reason: d.failureReason }) : null} />
          <p class={styles.moneyNote}>{t('hint.moneyNotMoved')}</p>
          {d ? <AmountDisplay amountKobo={d.amountKobo} compact /> : null}
        </section>
        <div class="page-bottom">
          <BigButton onClick={dismissResult}>{t('voice.done')}</BigButton>
        </div>
      </>
    )
  }
  return (
    <section class={styles.center} data-panel="pending">
      <span class={styles.spinner} aria-hidden="true" />
      <StatusPanel icon="clock" tone="warning" status={t('status.pending')} line={t('hint.pending')} />
      {d ? <AmountDisplay amountKobo={d.amountKobo} compact /> : null}
    </section>
  )
}

function CancelledPanel() {
  const expired = cancelKind.value === 'expired'
  return (
    <>
      <section class={styles.center} data-panel="cancelled">
        <StatusPanel icon="cross" tone="neutral" status={expired ? t('status.expired') : t('status.cancelled')} line={null} />
      </section>
      <div class="page-bottom">
        <BigButton variant="secondary" onClick={dismissResult}>
          {t('voice.done')}
        </BigButton>
      </div>
    </>
  )
}
