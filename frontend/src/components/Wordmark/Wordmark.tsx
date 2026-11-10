import { useRef } from 'preact/hooks'
import { env } from '../../config/env'
import { devPanelOpen } from '../../session/session'
import styles from './Wordmark.module.css'

/** Text logo. Five quick taps open the dev panel (only when VITE_DEV_PANEL=true). */
export function Wordmark({ size = 'md' }: { size?: 'sm' | 'md' | 'lg' }) {
  const taps = useRef<number[]>([])
  const onTap = () => {
    if (!env.DEV_PANEL) return
    const now = Date.now()
    taps.current = [...taps.current.filter((t) => now - t < 2000), now]
    if (taps.current.length >= 5) {
      taps.current = []
      devPanelOpen.value = true
    }
  }
  const inner = (
    <>
      Avenza<span class={styles.dot} aria-hidden="true" />
    </>
  )
  return env.DEV_PANEL ? (
    <button type="button" class={`${styles.mark} ${styles[size]} ${styles.btn}`} onClick={onTap} aria-label="Avenza">
      {inner}
    </button>
  ) : (
    <span class={`${styles.mark} ${styles[size]}`} role="img" aria-label="Avenza">
      {inner}
    </span>
  )
}
