import { Link } from '../../screens/Voice/Link'
import { Icon, type IconName } from '../Icon/Icon'
import { t } from '../../i18n'
import styles from './BottomNav.module.css'

type Tab = 'home' | 'transactions' | 'settings'
const tabs: Array<{ id: Tab; href: string; icon: IconName; label: string }> = [
  { id: 'home', href: '/', icon: 'home', label: 'nav.home' },
  { id: 'transactions', href: '/history', icon: 'history', label: 'nav.transactions' },
  { id: 'settings', href: '/settings', icon: 'settings', label: 'nav.settings' },
]

/** Bottom tab bar from the prototype. Voice stays the main way in; this is for people who prefer to tap. */
export function BottomNav({ active }: { active: Tab }) {
  return (
    <nav class={styles.nav} aria-label={t('nav.label')}>
      {tabs.map((tab) => (
        <Link
          key={tab.id}
          href={tab.href}
          class={`${styles.tab} ${tab.id === active ? styles.active : ''}`}
          aria-current={tab.id === active ? 'page' : undefined}
        >
          <Icon name={tab.icon} size={22} />
          <span>{t(tab.label)}</span>
        </Link>
      ))}
    </nav>
  )
}
