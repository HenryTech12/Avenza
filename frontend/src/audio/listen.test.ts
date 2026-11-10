import { describe, expect, it } from 'vitest'
import { isAgreement, languageFrom, nameFrom } from './listen'

describe('spoken onboarding answers', () => {
  it('accepts agreement and refuses a negative', () => {
    for (const s of ['I agree', 'yes I agree', 'Okay.', 'Yes', 'agreed']) expect(isAgreement(s), s).toBe(true)
    for (const s of ['I do not agree', "I don't agree", 'no', 'not now', 'hello', 'I need to think', 'eh?']) expect(isAgreement(s), s).toBe(false)
  })
  it('accepts agreement in Yoruba, Hausa and Igbo (beta)', () => {
    for (const s of ['Mo gbà', 'Na yarda', 'Ekwere m', 'Bẹ́ẹ̀ni']) expect(isAgreement(s), s).toBe(true)
    for (const s of ['Rárá', "A'a", 'Mba', 'Ban yarda ba']) expect(isAgreement(s), s).toBe(false)
  })
  it('hears the language the customer names', () => {
    expect(languageFrom('Yoruba please')).toBe('yo')
    expect(languageFrom('I want Hausa')).toBe('ha')
    expect(languageFrom('Igbo')).toBe('ig')
    expect(languageFrom('English')).toBe('en')
    expect(languageFrom('Yorùbá')).toBe('yo')
    expect(languageFrom('hello')).toBeNull()
  })
  it('takes the name out of a sentence', () => {
    expect(nameFrom('my name is ngozi adaobi eze')).toBe('Ngozi Adaobi Eze')
    expect(nameFrom("I'm Tunde.")).toBe('Tunde')
    expect(nameFrom('Chukwuemeka')).toBe('Chukwuemeka')
  })
})

describe('ask: question, listen, ask again', () => {
  it('asks again when nothing usable is heard, then stops once the answer comes', async () => {
    const { ask } = await import('./listen')
    const heardSequence = ['', 'hmm', 'Yoruba please']
    let starts = 0
    class FakeRec {
      lang = ''; continuous = false; interimResults = false; maxAlternatives = 1
      onresult: ((e: unknown) => void) | null = null
      onend: (() => void) | null = null
      onerror: ((e: unknown) => void) | null = null
      start() {
        const text = heardSequence[Math.min(starts++, heardSequence.length - 1)]
        setTimeout(() => {
          if (text) this.onresult?.({ results: [[{ transcript: text }]] })
          this.onend?.()
        }, 1)
      }
      stop() {}
      abort() {}
    }
    ;(globalThis as unknown as { webkitSpeechRecognition: unknown }).webkitSpeechRecognition = FakeRec
    const said: number[] = []
    let answer = ''
    await new Promise<void>((done) => {
      ask({
        lang: 'en-NG',
        say: async (n) => { said.push(n) },
        onText: (t) => {
          if (!/yoruba/i.test(t)) return false
          answer = t
          done()
          return true
        },
      })
    })
    expect(answer).toBe('Yoruba please')
    expect(said[0]).toBe(0)
    delete (globalThis as unknown as { webkitSpeechRecognition?: unknown }).webkitSpeechRecognition
  })

  it('gives up after the last try so the screen can fall back', async () => {
    const { ask } = await import('./listen')
    class SilentRec {
      lang = ''; continuous = false; interimResults = false; maxAlternatives = 1
      onresult = null; onerror = null
      onend: (() => void) | null = null
      start() { setTimeout(() => this.onend?.(), 1) }
      stop() {}
      abort() {}
    }
    ;(globalThis as unknown as { webkitSpeechRecognition: unknown }).webkitSpeechRecognition = SilentRec
    const said: number[] = []
    await new Promise<void>((done) => {
      ask({ lang: 'en-NG', tries: 2, say: async (n) => { said.push(n) }, onText: () => false, onGiveUp: done })
    })
    expect(said).toEqual([0, 1]) // asked, then asked again, then gave up
    delete (globalThis as unknown as { webkitSpeechRecognition?: unknown }).webkitSpeechRecognition
  })
})

describe('ask: when listening cannot work', () => {
  it('does not keep asking when the recogniser is unreachable', async () => {
    const { ask } = await import('./listen')
    class BrokenRec {
      lang = ''; continuous = false; interimResults = false; maxAlternatives = 1
      onresult = null
      onend: (() => void) | null = null
      onerror: ((e: { error: string }) => void) | null = null
      start() { setTimeout(() => { this.onerror?.({ error: 'network' }); this.onend?.() }, 1) }
      stop() {}
      abort() {}
    }
    ;(globalThis as unknown as { webkitSpeechRecognition: unknown }).webkitSpeechRecognition = BrokenRec
    const said: number[] = []
    await new Promise<void>((done) => {
      ask({ lang: 'en-NG', say: async (n) => { said.push(n) }, onText: () => false, onGiveUp: done })
    })
    expect(said).toEqual([0]) // asked once; the buttons take over
    delete (globalThis as unknown as { webkitSpeechRecognition?: unknown }).webkitSpeechRecognition
  })
})
