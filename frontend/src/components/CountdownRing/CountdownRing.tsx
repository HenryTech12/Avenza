import { useEffect, useState } from 'preact/hooks'
import { t } from '../../i18n'
import styles from './CountdownRing.module.css'

interface Props {
  /** epoch ms when the countdown ends */
  deadline: number
  totalMs: number
  size?: number
  tone?: 'accent' | 'warning'
}

export function CountdownRing({ deadline, totalMs, size = 96, tone = 'accent' }: Props) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 200)
    return () => clearInterval(id)
  }, [])
  const remaining = Math.max(0, deadline - now)
  const secs = Math.ceil(remaining / 1000)
  const stroke = 6
  const r = (size - stroke) / 2
  const circ = 2 * Math.PI * r
  const frac = totalMs > 0 ? Math.min(1, remaining / totalMs) : 0
  return (
    <div class={`${styles.wrap} ${styles[tone]}`} style={{ width: `${size}px`, height: `${size}px` }} role="timer" aria-label={t('voice.seconds', { n: secs })}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
        <circle cx={size / 2} cy={size / 2} r={r} class={styles.track} stroke-width={stroke} fill="none" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          class={styles.bar}
          stroke-width={stroke}
          fill="none"
          stroke-linecap="round"
          stroke-dasharray={circ}
          stroke-dashoffset={circ * (1 - frac)}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      </svg>
      <span class={`${styles.secs} tabular`} aria-hidden="true">
        {secs}
      </span>
    </div>
  )
}
