import { t } from '../../i18n'
import styles from './SimulatedBadge.module.css'

export function SimulatedBadge() {
  return (
    <span class={styles.badge} role="status" aria-label={t('common.simulatedLabel')}>
      <span class={styles.dot} aria-hidden="true" />
      {t('common.simulated')}
    </span>
  )
}
