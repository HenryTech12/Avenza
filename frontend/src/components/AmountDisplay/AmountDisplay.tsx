import { amountInWords, formatNaira } from '../../lib/format'
import styles from './AmountDisplay.module.css'

/** Amount exactly as the server sent it (kobo), formatted for display, plus the spoken words. */
export function AmountDisplay({ amountKobo, compact = false }: { amountKobo: number; compact?: boolean }) {
  const words = amountInWords(amountKobo)
  return (
    <div class={`${styles.wrap} ${compact ? styles.compact : ''}`}>
      <p class={`${styles.amount} tabular`} aria-label={words}>
        {formatNaira(amountKobo)}
      </p>
      <p class={styles.words}>{words}</p>
    </div>
  )
}
