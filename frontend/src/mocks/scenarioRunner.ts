import type { ClientMessage, ServerMessage, TransferDraft, TransferState, Lang } from '../protocol/messages'
import { amountInWords } from '../lib/format'
import { getScenario, type Answer, type Scenario } from './scenarios'

export interface RunnerIO {
  emit(msg: ServerMessage): void
  /** simulate a connection drop and recovery */
  drop(forMs: number): void
}

type Phase = 'idle' | 'readback' | 'awaiting' | 'submitted' | 'done'

/**
 * Plays the "server" side of a scenario. Pure logic plus timers; no browser APIs,
 * so it is unit-testable with fake timers.
 *
 * Mock-only convention: `prompt.play { clipUrl: 'speak:<text>' }` asks the client to speak
 * that text (the real server will send audio.stream instead).
 */
export class ScenarioRunner {
  private phase: Phase = 'idle'
  private answerIndex = 0
  private unclearCount = 0
  private transferId = ''
  private timers = new Set<ReturnType<typeof setTimeout>>()
  private scenario: Scenario
  private counter = 0
  private lang: Lang = 'en'

  constructor(
    private io: RunnerIO,
    scenarioId: string,
  ) {
    this.scenario = getScenario(scenarioId)
  }

  setScenario(id: string): void {
    this.scenario = getScenario(id)
    this.reset()
  }

  get scenarioId(): string {
    return this.scenario.id
  }

  stop(): void {
    for (const t of this.timers) clearTimeout(t)
    this.timers.clear()
  }

  reset(): void {
    this.stop()
    this.phase = 'idle'
    this.answerIndex = 0
    this.unclearCount = 0
  }

  private later(fn: () => void, ms: number): void {
    const t = setTimeout(() => {
      this.timers.delete(t)
      fn()
    }, ms)
    this.timers.add(t)
  }

  private jitter(): number {
    const d = this.scenario.delayMs
    return d ? d[0] + Math.random() * (d[1] - d[0]) : 0
  }

  /** Emit after `ms` (plus scenario network delay). Sequential steps use cumulative offsets. */
  private send(msg: ServerMessage, ms = 0): void {
    this.later(() => this.io.emit(msg), ms + this.jitter())
  }

  private state(state: TransferState, ms: number, draft?: TransferDraft) {
    this.send({ type: 'state.changed', transferId: this.transferId, state, draft }, ms)
  }

  private speak(text: string, ms: number): void {
    this.send({ type: 'prompt.play', clipUrl: `speak:${text}` }, ms)
  }

  private readbackText(d: TransferDraft): string {
    return `Send ${amountInWords(d.amountKobo)} to ${d.recipientName} at ${d.bankName}, account ending ${d.accountMasked.replace(/\D/g, '')}.`
  }

  onClient(msg: ClientMessage): void {
    switch (msg.type) {
      case 'session.start':
        this.lang = msg.language
        this.reset()
        this.send({ type: 'listening' }, 200)
        break
      case 'utterance.end':
        this.onUtteranceEnd()
        break
      case 'confirm.response':
        this.onAnswer(msg.answer)
        break
      case 'approval.response':
        this.onApproval()
        break
      default:
        break
    }
  }

  /** Re-send the current state after a simulated reconnect. */
  resyncAfterReconnect(): void {
    if (this.phase === 'awaiting') {
      this.sendApprovalRequest(0)
    } else {
      this.send({ type: 'listening' }, 100)
    }
  }

  private onUtteranceEnd(): void {
    const s = this.scenario
    if (this.phase === 'idle') {
      if (s.providerDown) {
        this.send({ type: 'error', code: 'provider_down', promptId: 'err_provider_down' }, 600)
        this.send({ type: 'listening' }, 700)
        return
      }
      this.transferId = `tr_${Date.now().toString(36)}${++this.counter}`
      this.send({ type: 'transcript.final', text: s.transcript }, 500)
      this.state('DRAFTED', 650, s.draft)
      this.sendReadback(900)
    } else if (this.phase === 'readback') {
      this.onAnswer(s.answers[Math.min(this.answerIndex++, s.answers.length - 1)])
    }
  }

  private sendReadback(ms: number): void {
    const d = this.scenario.draft
    this.phase = 'readback'
    this.state('READBACK_PLAYED', ms, d)
    this.speak(this.readbackText(d), ms + 50)
    this.speak('Say yes, no, or repeat.', ms + 100)
    this.send({ type: 'listening' }, ms + 150)
  }

  private onAnswer(answer: Answer): void {
    if (this.phase === 'awaiting') {
      // client-side fingerprint failure/cancel arrives as confirm.response "no"
      if (answer === 'no') this.cancel('CANCELLED', 100)
      return
    }
    if (this.phase !== 'readback') return
    const s = this.scenario
    switch (answer) {
      case 'yes':
        this.state('CONFIRMED_BY_VOICE', 200, s.draft)
        this.sendApprovalRequest(350)
        break
      case 'no':
        this.cancel('CANCELLED', 300)
        break
      case 'repeat':
        this.sendReadback(300)
        break
      case 'unclear':
        this.unclearCount++
        if (this.unclearCount >= 2) {
          this.cancel('CANCELLED', 400)
        } else {
          this.send({ type: 'error', code: 'unclear_reply', promptId: 'say_yes_no_repeat' }, 400)
          this.send({ type: 'listening' }, 500)
        }
        break
    }
  }

  private sendApprovalRequest(ms: number): void {
    const s = this.scenario
    this.phase = 'awaiting'
    this.state('AWAITING_BIOMETRIC', ms, s.draft)
    this.send(
      {
        type: 'approval.request',
        transferId: this.transferId,
        options: {
          challenge: btoa(`mock-${this.transferId}-${Date.now()}`).replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_'),
          timeout: 60000,
          userVerification: 'required',
          rpId: typeof location === 'undefined' ? 'localhost' : location.hostname,
          allowCredentials: [],
        },
      },
      ms + 50,
    )
    if (s.dropDuringFingerprint && !this.dropped) {
      this.dropped = true
      this.later(() => this.io.drop(3000), ms + 600)
    }
    if (s.fingerprint === 'expire') {
      this.later(() => {
        if (this.phase === 'awaiting') this.cancel('EXPIRED', 0)
      }, ms + (s.expireAfterMs ?? 15000))
    }
  }
  private dropped = false

  private onApproval(): void {
    if (this.phase !== 'awaiting') return
    const s = this.scenario
    this.phase = 'submitted'
    this.state('APPROVED', 250, s.draft)
    this.state('SUBMITTED', 900, s.draft)
    const ref = `AVZ${Date.now().toString().slice(-9)}`
    if (s.outcome === 'settled') {
      this.finish('SETTLED', 2200, { ...s.draft, reference: ref })
    } else if (s.outcome === 'pending_then_settled') {
      this.state('PENDING_UNKNOWN', 1800, s.draft)
      this.finish('SETTLED', 5800, { ...s.draft, reference: ref })
    } else {
      this.finish('FAILED', 2200, { ...s.draft, failureReason: s.failureReason ?? 'The transfer failed' })
    }
  }

  private finish(state: 'SETTLED' | 'FAILED', ms: number, draft: TransferDraft): void {
    this.state(state, ms, draft)
    this.later(() => {
      this.phase = 'done'
    }, ms)
    // after the client's return window, the server is ready for a new request
    this.later(() => {
      this.reset()
      this.io.emit({ type: 'listening' })
    }, ms + 3400)
  }

  private cancel(state: 'CANCELLED' | 'EXPIRED', ms: number): void {
    this.phase = 'done'
    this.state(state, ms)
    this.later(() => {
      this.reset()
      this.io.emit({ type: 'listening' })
    }, ms + 3400)
  }

  get languageCode(): Lang {
    return this.lang
  }
}
