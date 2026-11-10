import { registerSW } from 'virtual:pwa-register'
import { notifyUpdateAvailable } from '../session/session'

let update: ((reload?: boolean) => Promise<void>) | null = null

/** Register the service worker; shows a toast when a new version is waiting. */
export function registerServiceWorker(): void {
  if (!('serviceWorker' in navigator)) return
  update = registerSW({
    onNeedRefresh: () => notifyUpdateAvailable(),
    onRegisterError: (e) => console.warn('[avenza] service worker error', e),
  })
}

export function applyServiceWorkerUpdate(): void {
  void update?.(true)
}
