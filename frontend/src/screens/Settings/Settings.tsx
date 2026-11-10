import { useEffect, useRef, useState } from 'preact/hooks'
import { useLocation } from 'preact-iso'
import { Icon } from '../../components/Icon/Icon'
import { Sheet } from '../../components/Sheet/Sheet'
import { BigButton } from '../../components/BigButton/BigButton'
import {
  language, languages, chooseLanguage, theme, highContrast, withdrawConsent, bankMode, bankSimulated, env, flags, notify, lockTransfers,
} from '../../session/session'
import {
  fetchProfile, fetchBalance, fetchConfig, chooseSourceAccount, errorText,
  type Me, type Balance, type SourceAccount,
} from '../../session/account'
import { ApiError } from '../../api/http'
import type { Theme } from '../../lib/settings'
import { t } from '../../i18n'
import styles from './Settings.module.css'

const BUILD = (import.meta.env.VITE_BUILD_HASH as string | undefined) ?? 'dev'
const VERSION = '0.1.0'

type Account =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; me: Me; balance: Balance | null; sources: SourceAccount[] }

function useAccount() {
  const [account, setAccount] = useState<Account>({ status: 'loading' })
  const [reload, setReload] = useState(0)
  useEffect(() => {
    let cancelled = false
    setAccount({ status: 'loading' })
    Promise.all([
      fetchProfile(),
      fetchBalance().catch((e) => {
        // the mock bank has no balance (404); a bank outage is not worth blocking the screen for
        if (e instanceof ApiError) return null
        throw e
      }),
      fetchConfig().then((c) => c.sourceAccounts).catch(() => [] as SourceAccount[]),
    ])
      .then(([me, balance, sources]) => !cancelled && setAccount({ status: 'ready', me, balance, sources }))
      .catch((e) => !cancelled && setAccount({ status: 'error', message: errorText(e) }))
    return () => {
      cancelled = true
    }
  }, [reload])
  return { account, refresh: () => setReload((n) => n + 1) }
}

const last4 = (n: string) => `•••• ${n.slice(-4)}`

export function Settings() {
  const { route } = useLocation()
  const heading = useRef<HTMLHeadingElement>(null)
  const [withdraw, setWithdraw] = useState(false)
  const [langOpen, setLangOpen] = useState(false)
  const [sourceOpen, setSourceOpen] = useState(false)
  const [lockOpen, setLockOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const { account, refresh } = useAccount()
  useEffect(() => heading.current?.focus({ preventScroll: true }), [])

  const themes: Theme[] = ['system', 'dark', 'light']
  const langName = languages.find((l) => l.code === language.value)?.name ?? ''

  const doWithdraw = () => {
    withdrawConsent()
    route('/onboarding/language', true)
  }

  return (
    <main class="page">
      <header class={styles.head}>
        <button type="button" class={styles.back} onClick={() => route('/')} aria-label={t('common.back')}>
          <Icon name="arrow-left" />
        </button>
        <h1 tabIndex={-1} ref={heading}>
          {t('settings.title')}
        </h1>
      </header>

      <section class={styles.group} aria-labelledby="account-h" aria-busy={account.status === 'loading'}>
        <h2 id="account-h" class={styles.groupTitle}>{t('settings.account')}</h2>
        {account.status === 'loading' ? (
          <p class={`${styles.row} muted`} role="status">{t('settings.loading')}…</p>
        ) : account.status === 'error' ? (
          <div class={styles.row} role="alert">
            <span class={styles.label}>{account.message}</span>
            <button type="button" class={styles.seg} onClick={refresh}>{t('settings.retry')}</button>
          </div>
        ) : (
          <>
            <div class={styles.row}>
              <span class={styles.label}>{t('settings.name')}</span>
              <span class={styles.value}>{account.me.displayName}</span>
            </div>
            <div class={styles.row}>
              <span class={styles.label}>{t('settings.balance')}</span>
              <span class={`${styles.value} tabular`}>{account.balance?.availableDisplay ?? t('settings.balanceUnavailable')}</span>
            </div>
            {account.sources.length > 0 ? (
              <button type="button" class={styles.row} onClick={() => setSourceOpen(true)}>
                <span class={styles.label}>{t('settings.sourceAccount')}</span>
                <span class={`${styles.value} tabular`}>{account.me.sourceAccount ? last4(account.me.sourceAccount) : '—'}</span>
                <Icon name="chevron" size={20} />
              </button>
            ) : null}
          </>
        )}
      </section>

      <section class={styles.group} aria-label={t('settings.title')}>
        <button type="button" class={styles.row} onClick={() => setLangOpen(true)}>
          <span class={styles.label}>{t('settings.language')}</span>
          <span class={styles.value}>{langName}</span>
          <Icon name="chevron" size={20} />
        </button>

        <div class={styles.row} role="group" aria-labelledby="theme-label">
          <span class={styles.label} id="theme-label">{t('settings.theme')}</span>
          <div class={styles.segment}>
            {themes.map((th) => (
              <button
                key={th}
                type="button"
                class={`${styles.seg} ${theme.value === th ? styles.segOn : ''}`}
                aria-pressed={theme.value === th}
                onClick={() => (theme.value = th)}
              >
                {t(`settings.theme.${th}`)}
              </button>
            ))}
          </div>
        </div>

        <label class={styles.row}>
          <span class={styles.label}>{t('settings.contrast')}</span>
          <input
            type="checkbox"
            role="switch"
            class={styles.switch}
            checked={highContrast.value}
            onChange={(e) => (highContrast.value = (e.currentTarget as HTMLInputElement).checked)}
          />
        </label>

        <button type="button" class={styles.row} onClick={() => route('/onboarding/fingerprint')}>
          <span class={styles.label}>{t('settings.refinger')}</span>
          <Icon name="chevron" size={20} />
        </button>

        {flags.history ? (
          <button type="button" class={styles.row} onClick={() => route('/history')}>
            <span class={styles.label}>{t('history.title')}</span>
            <Icon name="chevron" size={20} />
          </button>
        ) : null}
        {flags.emergencyLock ? (
          <button type="button" class={styles.row} onClick={() => setLockOpen(true)}>
            <span class={styles.label}>{t('settings.lockNow')}</span>
            <Icon name="lock" size={20} />
          </button>
        ) : null}
      </section>

      <section class={styles.group}>
        <button type="button" class={`${styles.row} ${styles.dangerRow}`} onClick={() => setWithdraw(true)}>
          <span class={styles.label}>{t('settings.withdraw')}</span>
        </button>
      </section>

      <section class={styles.group} aria-labelledby="about-h">
        <h2 id="about-h" class={styles.groupTitle}>{t('settings.about')}</h2>
        <dl class={styles.about}>
          <div><dt>{t('settings.version')}</dt><dd>{VERSION}</dd></div>
          <div><dt>{t('settings.build')}</dt><dd>{BUILD}</dd></div>
          <div><dt>{t('settings.backend')}</dt><dd>{env.BACKEND_MODE}</dd></div>
          <div><dt>{t('settings.bank')}</dt><dd>{bankMode.value ?? '—'}{bankSimulated.value ? ` · ${t('common.simulated')}` : ''}</dd></div>
        </dl>
      </section>

      {withdraw ? (
        <Sheet title={t('settings.withdrawTitle')} icon="warning" tone="danger" message={t('settings.withdrawBody')} onClose={() => setWithdraw(false)}>
          <BigButton variant="danger" onClick={doWithdraw}>{t('settings.withdrawConfirm')}</BigButton>
          <BigButton variant="secondary" onClick={() => setWithdraw(false)}>{t('common.cancel')}</BigButton>
        </Sheet>
      ) : null}

      {lockOpen ? (
        <Sheet title={t('settings.lockNowTitle')} icon="lock" message={t('settings.lockNowBody')} onClose={() => setLockOpen(false)}>
          <BigButton
            variant="danger"
            onClick={async () => {
              setLockOpen(false)
              await lockTransfers()
              route('/lock')
            }}
          >
            {t('settings.lockNowConfirm')}
          </BigButton>
          <BigButton variant="secondary" onClick={() => setLockOpen(false)}>{t('common.cancel')}</BigButton>
        </Sheet>
      ) : null}

      {sourceOpen && account.status === 'ready' ? (
        <Sheet title={t('settings.sourceAccountTitle')} onClose={() => setSourceOpen(false)}>
          {account.sources.map((a) => (
            <BigButton
              key={a.accountNumber}
              variant={account.me.sourceAccount === a.accountNumber ? 'primary' : 'secondary'}
              loading={saving}
              onClick={async () => {
                setSaving(true)
                try {
                  await chooseSourceAccount(a.accountNumber)
                  notify(t('settings.sourceSaved'))
                  setSourceOpen(false)
                  refresh()
                } catch (e) {
                  notify(errorText(e))
                } finally {
                  setSaving(false)
                }
              }}
            >
              {a.accountName} · {last4(a.accountNumber)}
            </BigButton>
          ))}
        </Sheet>
      ) : null}

      {langOpen ? (
        <Sheet title={t('settings.language')} onClose={() => setLangOpen(false)}>
          {languages.map((l) => (
            <BigButton
              key={l.code}
              variant={language.value === l.code ? 'primary' : 'secondary'}
              disabled={!l.enabled}
              onClick={async () => {
                await chooseLanguage(l.code)
                setLangOpen(false)
              }}
            >
              {l.name}
              {!l.enabled ? ` · ${t('language.comingSoon')}` : ''}
            </BigButton>
          ))}
        </Sheet>
      ) : null}
    </main>
  )
}
