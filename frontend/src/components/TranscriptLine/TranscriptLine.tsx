import { t } from '../../i18n'
import styles from './TranscriptLine.module.css'

export function TranscriptLine({ text, partial = false }: { text: string; partial?: boolean }) {
  if (!text) return <div class={styles.placeholder} aria-hidden="true" />
  return <p class={styles.line}>{partial ? text : t('voice.heard', { text })}</p>
}
