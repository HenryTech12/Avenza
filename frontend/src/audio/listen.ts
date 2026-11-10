/**
 * Short spoken answers during onboarding ("I agree", the customer's name), before the device is
 * enrolled and the voice WebSocket can be used. Uses the browser's own speech recognition when it
 * has one; every step keeps its button, so nothing depends on this.
 */
type Rec = {
  lang: string
  continuous: boolean
  interimResults: boolean
  maxAlternatives: number
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null
  onend: (() => void) | null
  onerror: ((e: { error?: string }) => void) | null
  start(): void
  stop(): void
  abort(): void
}

function ctor(): (new () => Rec) | null {
  const w = globalThis as unknown as { SpeechRecognition?: new () => Rec; webkitSpeechRecognition?: new () => Rec }
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null
}

export const voiceAnswersSupported = () => ctor() !== null

/**
 * Listen until `onText` returns true, the caller stops it, or it gives up (about a minute).
 * Returns a stop function. Errors such as "no microphone" or "not allowed" end it quietly.
 */
export function listenFor(lang: string, onText: (text: string) => boolean, onHeard?: (text: string) => void): () => void {
  const C = ctor()
  if (!C) return () => undefined
  let stopped = false
  let rounds = 0
  let rec: Rec | null = null
  const run = () => {
    if (stopped || rounds++ > 8) return
    rec = new C()
    rec.lang = lang
    rec.continuous = false
    rec.interimResults = false
    rec.maxAlternatives = 3
    rec.onresult = (e) => {
      const alts = Array.from(e.results[e.results.length - 1] ?? []).map((a) => a.transcript.trim()).filter(Boolean)
      if (alts[0]) onHeard?.(alts[0])
      if (alts.some((a) => onText(a))) stop()
    }
    rec.onerror = (e) => {
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed' || e.error === 'audio-capture') stopped = true
    }
    rec.onend = () => {
      if (!stopped) setTimeout(run, 250)
    }
    try {
      rec.start()
    } catch {
      stopped = true
    }
  }
  const stop = () => {
    stopped = true
    try {
      rec?.abort()
    } catch {
      /* already stopped */
    }
  }
  run()
  return stop
}

/** "I agree", "yes I agree", "okay", "yes" count as agreeing; anything with "not" or "don't" does not. */
export function isAgreement(text: string): boolean {
  const s = text.toLowerCase()
  if (/\b(not|don't|do not|no)\b/.test(s)) return false
  return /\b(i agree|agree|agreed|yes|okay|ok|accept)\b/.test(s)
}

/** "My name is Ngozi Eze" -> "Ngozi Eze". */
export function nameFrom(text: string): string {
  const s = text.trim().replace(/[.!?]+$/, '')
  const m = s.match(/(?:my name is|i am|i'm|call me|it's|this is)\s+(.+)$/i)
  const name = (m ? m[1] : s).trim()
  return name
    .split(/\s+/)
    .slice(0, 4)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}
