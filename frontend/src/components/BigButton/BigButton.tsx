import type { ComponentChildren, ButtonHTMLAttributes } from 'preact'
import styles from './BigButton.module.css'

interface Props extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'loading'> {
  variant?: 'primary' | 'secondary' | 'danger'
  loading?: boolean
  children: ComponentChildren
}

export function BigButton({ variant = 'primary', loading, disabled, children, class: cls, ...rest }: Props) {
  return (
    <button
      type="button"
      class={`${styles.btn} ${styles[variant]} ${cls ?? ''}`}
      disabled={disabled || loading}
      aria-busy={loading ? 'true' : undefined}
      {...rest}
    >
      {loading ? <span class={styles.spinner} aria-hidden="true" /> : null}
      <span class={styles.label}>{children}</span>
    </button>
  )
}
