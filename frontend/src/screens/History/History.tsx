import { useEffect, useRef, useState } from 'preact/hooks'
import { useLocation } from 'preact-iso'
import { Icon, type IconName } from '../../components/Icon/Icon'
import { Sheet } from '../../components/Sheet/Sheet'
import { BigButton } from '../../components/BigButton/BigButton'
import { AmountDisplay } from '../../components/AmountDisplay/AmountDisplay'
import { fetchHistory, fetchReceipt, errorText, type HistoryItem, type Receipt } from '../../session/account'
import { formatNaira } from '../../lib/format'
import { t } from '../../i18n'
import { BottomNav } from '../../components/BottomNav/BottomNav'
import styles from './History.module.css'

const RANGES = [7, 30, 90] as const
const PAGE = 25
const MAX = 100 // the backend's limit

type Tone = 'settled' | 'failed' | 'cancelled' | 'pending'
const chip: Record<Tone, IconName> = { settled: 'check', failed: 'cross', cancelled: 'cross', pending: 'history' }

function toneOf(state: string): { tone: Tone; label: string } {
  switch (state) {
    case 'SETTLED':
      return { tone: 'settled', label: 'status.chip.settled' }
    case 'FAILED':
      return { tone: 'failed', label: 'status.chip.failed' }
    case 'REVERSED':
      return { tone: 'failed', label: 'status.chip.reversed' }
    case 'CANCELLED':
    case 'EXPIRED':
      return { tone: 'cancelled', label: 'status.chip.cancelled' }
    default:
      return { tone: 'pending', label: 'status.chip.pending' }
  }
}

const dateFmt = new Intl.DateTimeFormat('en-NG', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
const when = (iso: string | null) => (iso && !Number.isNaN(Date.parse(iso)) ? dateFmt.format(new Date(iso)) : '')

function bankLine(i: HistoryItem): string {
  return [i.bankName, i.accountLast4 ? `•••• ${i.accountLast4}` : ''].filter(Boolean).join(' ')
}

const naira = (v: number | string | null) => (typeof v === 'number' ? formatNaira(v) : (v ?? ''))

type Load = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; items: HistoryItem[] }

export function History() {
  const { route } = useLocation()
  const heading = useRef<HTMLHeadingElement>(null)
  const [days, setDays] = useState<(typeof RANGES)[number]>(30)
  const [limit, setLimit] = useState(PAGE)
  const [query, setQuery] = useState('')
  const [load, setLoad] = useState<Load>({ status: 'loading' })
  const [retry, setRetry] = useState(0)
  const [open, setOpen] = useState<HistoryItem | null>(null)
  useEffect(() => heading.current?.focus({ preventScroll: true }), [])

  useEffect(() => {
    let cancelled = false
    setLoad((l) => (l.status === 'ready' ? l : { status: 'loading' }))
    const end = new Date()
    const start = new Date(end.getTime() - days * 86_400_000)
    fetchHistory({ start: start.toISOString(), end: end.toISOString(), limit })
      .then((h) => !cancelled && setLoad({ status: 'ready', items: h.items }))
      .catch((e) => !cancelled && setLoad({ status: 'error', message: errorText(e) }))
    return () => {
      cancelled = true
    }
  }, [days, limit, retry])

  const items = load.status === 'ready' ? load.items : []
  const q = query.trim().toLowerCase()
  const shown = q ? items.filter((i) => `${i.recipient} ${i.reference ?? ''} ${i.bankName ?? ''}`.toLowerCase().includes(q)) : items
  const canMore = load.status === 'ready' && items.length >= limit && limit < MAX

  return (
    <main class="page">
      <header class={styles.head}>
        <button type="button" class={styles.back} onClick={() => route('/')} aria-label={t('common.back')}>
          <Icon name="arrow-left" />
        </button>
        <h1 tabIndex={-1} ref={heading}>{t('history.title')}</h1>
      </header>

      <div class={styles.filters}>
        <div class={styles.segment} role="group" aria-label={t('history.range')}>
          {RANGES.map((d) => (
            <button
              key={d}
              type="button"
              class={`${styles.seg} ${days === d ? styles.segOn : ''}`}
              aria-pressed={days === d}
              onClick={() => {
                setDays(d)
                setLimit(PAGE)
              }}
            >
              {t(`history.range${d}`)}
            </button>
          ))}
        </div>
        <input
          class={styles.search}
          type="search"
          inputMode="search"
          aria-label={t('history.search')}
          placeholder={t('history.search')}
          value={query}
          onInput={(e) => setQuery((e.currentTarget as HTMLInputElement).value)}
        />
      </div>

      {load.status === 'loading' ? (
        <div class="page-center" role="status" aria-busy="true">
          <Icon name="history" size={40} />
          <p class="muted">{t('settings.loading')}…</p>
        </div>
      ) : load.status === 'error' ? (
        <div class="page-center" role="alert">
          <Icon name="warning" size={40} />
          <p>{t('history.error')}</p>
          <p class="muted">{load.message}</p>
          <BigButton variant="secondary" onClick={() => setRetry((n) => n + 1)}>{t('common.retry')}</BigButton>
        </div>
      ) : shown.length === 0 ? (
        <div class="page-center">
          <Icon name="history" size={40} />
          <p class="muted">{q ? t('history.noMatch') : t('history.empty')}</p>
        </div>
      ) : (
        <>
          <ul class={styles.list}>
            {shown.map((r, n) => {
              const { tone, label } = toneOf(r.state)
              return (
                <li key={r.id ?? `${r.reference}-${n}`}>
                  <button type="button" class={styles.item} onClick={() => setOpen(r)}>
                    <span class={styles.avatar} aria-hidden="true">{(r.recipient || '?').trim().charAt(0).toUpperCase()}</span>
                    <span class={styles.main}>
                      <span class={styles.name}>{r.recipient || '—'}</span>
                      <span class={styles.date}>{when(r.createdAt)}</span>
                    </span>
                    <span class={styles.side}>
                      <span class={`${styles.amt} tabular`}>− {formatNaira(r.amountKobo)}</span>
                      <span class={`${styles.chip} ${styles[tone]}`}>
                        <Icon name={chip[tone]} size={14} />
                        {t(label)}
                      </span>
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
          {canMore ? <BigButton variant="secondary" onClick={() => setLimit((l) => Math.min(MAX, l + PAGE))}>{t('history.loadMore')}</BigButton> : null}
        </>
      )}
      {open ? <ReceiptSheet item={open} onClose={() => setOpen(null)} /> : null}
      <BottomNav active="transactions" />
    </main>
  )
}

function ReceiptSheet({ item, onClose }: { item: HistoryItem; onClose: () => void }) {
  const [receipt, setReceipt] = useState<Receipt | null>(null)
  const [state, setState] = useState<'idle' | 'loading' | 'error'>('idle')
  const [message, setMessage] = useState('')
  const sendable = !!item.id && !!item.reference

  useEffect(() => {
    if (!sendable) return
    let cancelled = false
    setState('loading')
    fetchReceipt(item.id as string)
      .then((r) => {
        if (cancelled) return
        setReceipt(r)
        setState('idle')
      })
      .catch((e) => {
        if (cancelled) return
        setMessage(errorText(e))
        setState('error')
      })
    return () => {
      cancelled = true
    }
  }, [item.id])

  const { label } = toneOf(item.state)
  return (
    <Sheet title={t('history.receipt')} message={`${item.recipient} · ${bankLine(item)}`} onClose={onClose}>
      <AmountDisplay amountKobo={item.amountKobo} compact />
      <dl class={styles.detail}>
        <div><dt>{t('history.status')}</dt><dd>{t(label)}</dd></div>
        {item.createdAt ? <div><dt>{t('voice.resultTime')}</dt><dd>{when(item.createdAt)}</dd></div> : null}
        {item.reference ? <div><dt>{t('voice.resultRef')}</dt><dd class="tabular">{item.reference}</dd></div> : null}
        {item.failureReason ? <div><dt>{t('history.reason')}</dt><dd>{item.failureReason.replaceAll('_', ' ')}</dd></div> : null}
        {receipt?.fee != null ? <div><dt>{t('history.fee')}</dt><dd class="tabular">{naira(receipt.fee)}</dd></div> : null}
        {receipt?.vat != null ? <div><dt>{t('history.vat')}</dt><dd class="tabular">{naira(receipt.vat)}</dd></div> : null}
        {receipt?.stampDuty != null ? <div><dt>{t('history.stamp')}</dt><dd class="tabular">{naira(receipt.stampDuty)}</dd></div> : null}
        {receipt?.totalDebit != null ? <div><dt>{t('history.total')}</dt><dd class="tabular">{naira(receipt.totalDebit)}</dd></div> : null}
      </dl>
      {!sendable ? <p class="muted">{t('history.noReceipt')}</p> : null}
      {state === 'loading' ? <p class="muted" role="status">{t('settings.loading')}…</p> : null}
      {state === 'error' ? <p class="muted" role="alert">{t('history.receiptError')} {message}</p> : null}
      <BigButton onClick={onClose}>{t('common.close')}</BigButton>
    </Sheet>
  )
}
