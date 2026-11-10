import type { ComponentChildren } from 'preact'
import styles from './Toast.module.css'

export function Toast({ children, action }: { children: ComponentChildren; action?: ComponentChildren }) {
  return (
    <div class={styles.toast} role="status">
      <span>{children}</span>
      {action}
    </div>
  )
}
