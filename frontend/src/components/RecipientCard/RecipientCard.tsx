import { Icon } from '../Icon/Icon'
import { t } from '../../i18n'
import styles from './RecipientCard.module.css'

interface Props {
  name: string
  bankName: string
  accountMasked: string
  isNewRecipient?: boolean
}

export function RecipientCard({ name, bankName, accountMasked, isNewRecipient }: Props) {
  return (
    <section class={styles.card} aria-label={t('voice.verified')}>
      <div class={styles.verified}>
        <Icon name="shield" size={18} />
        <span>{t('voice.verified')}</span>
        {isNewRecipient ? (
          <span class={styles.chip}>
            <Icon name="warning" size={14} />
            {t('voice.newRecipient')}
          </span>
        ) : null}
      </div>
      <p class={styles.name}>{name}</p>
      <p class={`${styles.bank} tabular`}>
        <Icon name="bank" size={18} />
        <span>
          {bankName} <span aria-hidden="true">·</span> {accountMasked}
        </span>
      </p>
    </section>
  )
}
