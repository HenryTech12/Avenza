import type { AnchorHTMLAttributes } from 'preact'
import { useLocation } from 'preact-iso'

/** Client-side link styled by the caller. */
export function Link({ href, children, ...rest }: AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) {
  const { route } = useLocation()
  return (
    <a
      href={href}
      {...rest}
      onClick={(e) => {
        if (e.metaKey || e.ctrlKey) return
        e.preventDefault()
        route(href)
      }}
    >
      {children}
    </a>
  )
}
