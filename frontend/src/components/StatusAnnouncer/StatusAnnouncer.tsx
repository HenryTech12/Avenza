import { announcement } from '../../session/session'

/** One visually hidden polite live region, mirroring what Avenza says. */
export function StatusAnnouncer() {
  return (
    <div class="sr-only" aria-live="polite" aria-atomic="true" data-testid="announcer">
      {announcement.value}
    </div>
  )
}
