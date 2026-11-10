import type { ComponentChildren } from 'preact'
import { useEffect, useRef } from 'preact/hooks'
import { Icon, type IconName } from '../Icon/Icon'
import styles from './StatusPanel.module.css'

export type Tone = 'neutral' | 'accent' | 'success' | 'warning' | 'danger'

interface Props {
  icon?: IconName
  tone?: Tone
  status: string
  line?: ComponentChildren
  /** Move focus to the heading when the panel appears (a new panel = a new context). */
  focusOnMount?: boolean
}

/** Icon + one big status word + one supporting line. Status is never colour alone. */
export function StatusPanel({ icon, tone = 'neutral', status, line, focusOnMount = true }: Props) {
  const ref = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    if (focusOnMount) ref.current?.focus({ preventScroll: true })
  }, [status, focusOnMount])
  return (
    <div class={styles.panel}>
      {icon ? (
        <span class={`${styles.icon} ${styles[tone]}`}>
          <Icon name={icon} size={28} />
        </span>
      ) : null}
      <h1 class={styles.status} tabIndex={-1} ref={ref}>
        {status}
      </h1>
      {line ? <p class={styles.line}>{line}</p> : null}
    </div>
  )
}
