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
export function listenFor(
  language: string,
  onText: (text: string) => boolean,
  onHeard?: (text: string) => void,
  opts: { rounds?: number; onGiveUp?: (why: 'silence' | 'unavailable') => void } = {},
): () => void {
  const C = ctor()
  if (!C) return () => undefined
  let lang = language
  let stopped = false
  let rounds = 0
  let rec: Rec | null = null
  const maxRounds = opts.rounds ?? 8
  let matched = false
  let unavailable = false
  let gaveUp = false
  const giveUp = () => {
    if (matched || gaveUp) return
    gaveUp = true
    opts.onGiveUp?.(unavailable ? 'unavailable' : 'silence')
  }
  const run = () => {
    if (stopped) return
    if (rounds++ >= maxRounds) {
      stopped = true
      giveUp()
      return
    }
    rec = new C()
    rec.lang = lang
    rec.continuous = false
    rec.interimResults = false
    rec.maxAlternatives = 3
    rec.onresult = (e) => {
      const alts = Array.from(e.results[e.results.length - 1] ?? []).map((a) => a.transcript.trim()).filter(Boolean)
      if (alts[0]) onHeard?.(alts[0])
      if (alts.some((a) => onText(a))) {
        matched = true
        stop()
      }
    }
    rec.onerror = (e) => {
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed' || e.error === 'audio-capture' || e.error === 'network') {
        // no microphone, not allowed, or the recogniser cannot be reached: asking again will not help
        unavailable = true
        stopped = true
        giveUp()
      }
      // Browsers without a Yoruba/Hausa/Igbo recogniser: listen in Nigerian English instead
      if (e.error === 'language-not-supported' && lang !== 'en-NG') lang = 'en-NG'
    }
    rec.onend = () => {
      if (!stopped) setTimeout(run, 250)
    }
    try {
      rec.start()
    } catch {
      unavailable = true
      stopped = true
      giveUp()
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

const plain = (text: string) => text.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '')

/**
 * Agreeing, in English or (beta) Yoruba, Hausa or Igbo: "I agree", "yes", "mo gba", "na yarda", "ekwere m".
 * Anything with a negation does not count.
 */
export function isAgreement(text: string): boolean {
  const s = plain(text)
  if (/\b(not|don't|do not|no|rara|a'a|aa|mba|ban yarda)\b/.test(s)) return false
  // en-NG recognisers write the local answers in many ways: "mo gba", "mogba", "na yarda", "nayarda", "a kwere m"
  return /\b(i agree|agree|agreed|yes|okay|ok|accept|mo gba|mogba|mo gbaa|beeni|mo fara mo|na yarda|nayarda|na amince|ekwere m|ekwerem|a kwere m|akwerem|ekwenyere m|ekwenyerem|ee)\b/.test(s)
}

/** "English", "Yoruba please", "Hausa", "Igbo", "Turanci" -> the language code, else null. */
export function languageFrom(text: string): 'en' | 'yo' | 'ha' | 'ig' | null {
  const s = plain(text)
  if (/\b(yoruba|yooba|yorba)\b/.test(s)) return 'yo'
  if (/\b(hausa|housa|hausa language)\b/.test(s)) return 'ha'
  if (/\b(igbo|ibo|eboh|igbo language)\b/.test(s)) return 'ig'
  if (/\b(english|turanci|oyinbo|bekee)\b/.test(s)) return 'en'
  return null
}

/** "My name is Ngozi Eze" -> "Ngozi Eze". */
export function nameFrom(text: string): string {
  const s = text.trim().replace(/[.!?]+$/, '')
  const m = s.match(/(?:my name is|i am|i'm|call me|it's|this is)\s+(.+)$/i)
  const name = (m ? m[1] : s).trim()
  return name
    .split(/\s+/)
    // speech recognition sometimes repeats a word ("Henry Henry", phone test 10 Nov)
    .filter((w, i, all) => i === 0 || w.toLowerCase() !== all[i - 1].toLowerCase())
    .slice(0, 4)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

/**
 * Ask a question out loud and listen for the answer; ask again when nothing usable is heard.
 * `say(n)` speaks the question (n = 0 the first time, so a long text can be shortened on repeats).
 * Returns a stop function. `onGiveUp` runs after the last try (the screen's buttons remain).
 */
export function ask(opts: {
  lang: string
  say: (attempt: number) => Promise<void>
  onText: (text: string) => boolean
  onHeard?: (text: string) => void
  onListening?: (on: boolean) => void
  tries?: number
  onGiveUp?: () => void
}): () => void {
  let stopped = false
  let stopListening: () => void = () => undefined
  const cycle = async (n: number) => {
    await opts.say(n)
    if (stopped) return
    opts.onListening?.(true)
    stopListening = listenFor(opts.lang, opts.onText, opts.onHeard, {
      rounds: 3,
      onGiveUp: (why) => {
        opts.onListening?.(false)
        if (stopped) return
        // Only ask again after real silence; if listening does not work at all, the screen's controls take over.
        if (why === 'silence' && n + 1 < (opts.tries ?? 4)) void cycle(n + 1)
        else opts.onGiveUp?.()
      },
    })
  }
  void cycle(0)
  return () => {
    stopped = true
    stopListening()
    opts.onListening?.(false)
  }
}
