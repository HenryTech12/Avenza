export const patterns = {
  listening: [30],
  readback: [30, 60, 30],
  fingerprint: [60],
  settled: [40, 40, 120],
  failed: [200],
} as const

export function vibrate(name: keyof typeof patterns): void {
  try {
    navigator.vibrate?.([...patterns[name]])
  } catch {
    /* unsupported */
  }
}
