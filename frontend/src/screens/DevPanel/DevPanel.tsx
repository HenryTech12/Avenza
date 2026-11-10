import { useEffect, useRef } from 'preact/hooks'
import {
  env, devPanelOpen, devSetBackend, devRunScenario, scenarioIds, scenarios, vadConfig, devApplyVad, showLatency, lastLatency,
  protocolLog, connection, devClearData, devClearOverride, flags, lockTransfers, showDuplicateNotice, bankMode,
} from '../../session/session'
import { BigButton } from '../../components/BigButton/BigButton'
import styles from './DevPanel.module.css'

const sliders = [
  { key: 'positiveSpeechThreshold', min: 0.2, max: 0.95, step: 0.01 },
  { key: 'negativeSpeechThreshold', min: 0.1, max: 0.9, step: 0.01 },
  { key: 'redemptionMs', min: 100, max: 1500, step: 50 },
  { key: 'minSpeechMs', min: 50, max: 800, step: 25 },
  { key: 'preSpeechPadMs', min: 0, max: 600, step: 20 },
] as const

const flagKeys = ['confirmButtons', 'showTranscript', 'history', 'scamPause', 'duplicateWarning', 'emergencyLock'] as const

/** Hidden developer overlay (five taps on the wordmark). Dev builds only. */
export function DevPanel() {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => ref.current?.focus(), [])
  const log = protocolLog.value.slice(-50).reverse()
  const lat = lastLatency.value

  return (
    <div class={styles.panel} role="dialog" aria-label="Developer panel" ref={ref} tabIndex={-1}>
      <header class={styles.head}>
        <h2>Developer panel</h2>
        <button type="button" class={styles.close} onClick={() => (devPanelOpen.value = false)}>Close</button>
      </header>

      {env.hasOverride() ? <p class={styles.override}>Runtime override active (this tab only)</p> : null}

      <section>
        <h3>Backend</h3>
        <div class={styles.row}>
          {(['mock', 'live'] as const).map((m) => (
            <button key={m} type="button" class={`${styles.pill} ${env.BACKEND_MODE === m ? styles.on : ''}`} aria-pressed={env.BACKEND_MODE === m} onClick={() => devSetBackend(m)}>
              {m}
            </button>
          ))}
        </div>
        <p class={styles.small}>Connection: {connection.value} · Bank: {bankMode.value ?? 'unknown'}</p>
      </section>

      <section>
        <h3>Scenario</h3>
        <label class={styles.field}>
          <span>Scenario</span>
          <select
            value={env.MOCK_SCENARIO}
            onChange={(e) => devRunScenario((e.currentTarget as HTMLSelectElement).value)}
            disabled={env.BACKEND_MODE !== 'mock'}
          >
            {scenarioIds.map((id) => (
              <option key={id} value={id}>{id}</option>
            ))}
          </select>
        </label>
        <p class={styles.small}>{scenarios[env.MOCK_SCENARIO]?.description}</p>
        <BigButton variant="secondary" onClick={() => devRunScenario(env.MOCK_SCENARIO)} disabled={env.BACKEND_MODE !== 'mock'}>
          Run scenario
        </BigButton>
      </section>

      <section>
        <h3>VAD thresholds</h3>
        {sliders.map((s) => (
          <label key={s.key} class={styles.field}>
            <span>{s.key}: <b>{vadConfig[s.key]}</b></span>
            <input
              type="range"
              min={s.min}
              max={s.max}
              step={s.step}
              value={vadConfig[s.key]}
              onInput={(e) => {
                vadConfig[s.key] = Number((e.currentTarget as HTMLInputElement).value)
                devApplyVad()
                ;(e.currentTarget.previousSibling?.lastChild as HTMLElement | null)?.replaceChildren(String(vadConfig[s.key]))
              }}
            />
          </label>
        ))}
      </section>

      <section>
        <h3>Latency</h3>
        <label class={styles.check}>
          <input type="checkbox" checked={showLatency.value} onChange={(e) => (showLatency.value = (e.currentTarget as HTMLInputElement).checked)} />
          Show overlay on Voice screen
        </label>
        <p class={styles.small}>
          End of speech to first sound: {lat.endToFirstSoundMs ?? '—'} ms · to read-back: {lat.endToReadbackMs ?? '—'} ms
        </p>
      </section>

      <section>
        <h3>Feature flags</h3>
        {flagKeys.map((k) => (
          <label key={k} class={styles.check}>
            <input
              type="checkbox"
              checked={flags[k]}
              onChange={(e) => {
                flags[k] = (e.currentTarget as HTMLInputElement).checked
                if (k === 'duplicateWarning' && flags[k]) showDuplicateNotice()
                if (k === 'emergencyLock' && flags[k]) devPanelOpen.value = true
              }}
            />
            {k}
          </label>
        ))}
        <div class={styles.row}>
          <button type="button" class={styles.pill} onClick={() => showDuplicateNotice()}>Show duplicate sheet</button>
          <button type="button" class={styles.pill} onClick={() => lockTransfers()}>Lock now</button>
        </div>
      </section>

      <section>
        <h3>Last 50 protocol messages</h3>
        <ol class={styles.log} aria-label="Protocol messages">
          {log.map((m, i) => (
            <li key={`${m.at}-${i}`}>
              <span class={m.dir === 'in' ? styles.in : styles.out}>{m.dir === 'in' ? '← server' : '→ client'}</span>
              <span>{m.type}</span>
              <time>{new Date(m.at).toLocaleTimeString()}</time>
            </li>
          ))}
        </ol>
      </section>

      <section class={styles.row}>
        <BigButton variant="danger" onClick={devClearData}>Clear local data</BigButton>
        <BigButton variant="secondary" onClick={devClearOverride}>Clear overrides</BigButton>
      </section>
    </div>
  )
}
