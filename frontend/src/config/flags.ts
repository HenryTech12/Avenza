/** Feature flags. All default false unless noted. Mutable so the dev panel can toggle them. */
export const flags = {
  confirmButtons: true, // default true; needs backend agreement (confirm.response)
  showTranscript: true, // default true
  history: true, // GET /transfers and receipts are live
  scamPause: false,
  duplicateWarning: false,
  emergencyLock: true, // POST /locks, /locks/options, /locks/unlock are live
}
export type Flags = typeof flags

// Dev builds only: `?flags=scamPause,emergencyLock` switches flags on for this page load (used by e2e tests).
if (import.meta.env.DEV && typeof location !== 'undefined') {
  const on = new URLSearchParams(location.search).get('flags')?.split(',') ?? []
  for (const k of on) if (k in flags) (flags as Record<string, boolean>)[k] = true
}
