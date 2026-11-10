import type { ComponentChildren } from 'preact'
import { useEffect, useRef } from 'preact/hooks'
import { Icon, type IconName } from '../Icon/Icon'
import styles from './Sheet.module.css'

interface Props {
  title: string
  message?: ComponentChildren
  icon?: IconName
  tone?: 'neutral' | 'danger' | 'warning'
  /** Escape / backdrop closes the sheet when provided */
  onClose?: () => void
  children?: ComponentChildren
}

const FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'

/** Bottom sheet. Traps focus; Escape closes when allowed. */
export function Sheet({ title, message, icon, tone = 'neutral', onClose, children }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const root = ref.current
    const first = root?.querySelector<HTMLElement>(FOCUSABLE)
    ;(first ?? root)?.focus({ preventScroll: true })
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && onClose) {
        e.preventDefault()
        onClose()
        return
      }
      if (e.key !== 'Tab' || !root) return
      const items = [...root.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => !el.hasAttribute('disabled'))
      if (items.length === 0) {
        e.preventDefault()
        return
      }
      const firstEl = items[0]
      const last = items[items.length - 1]
      if (e.shiftKey && document.activeElement === firstEl) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        firstEl.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      previous?.focus?.({ preventScroll: true })
    }
  }, [onClose])

  return (
    <div class={styles.overlay}>
      <div class={styles.backdrop} onClick={onClose} aria-hidden="true" />
      <div ref={ref} class={`${styles.sheet} ${styles[tone]}`} role="alertdialog" aria-modal="true" aria-labelledby="sheet-title" aria-describedby="sheet-msg" tabIndex={-1}>
        <span class={styles.grip} aria-hidden="true" />
        <div class={styles.head}>
          {icon ? (
            <span class={styles.icon}>
              <Icon name={icon} size={24} />
            </span>
          ) : null}
          <h2 id="sheet-title" class={styles.title}>
            {title}
          </h2>
        </div>
        {message ? (
          <p id="sheet-msg" class={styles.message}>
            {message}
          </p>
        ) : null}
        {children ? <div class={styles.actions}>{children}</div> : null}
      </div>
    </div>
  )
}
