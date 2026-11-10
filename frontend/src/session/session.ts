/**
 * The session: owns every signal the screens read and wires transport + audio + webauthn +
 * the pure state machine together. Screens import ONLY from `session/` (rule 8).
 */
import { signal, computed, effect } from '@preact/signals'
import { api, setUnauthorizedHandler } from '../api'
import { createTransport } from '../transport'
import { protocolLog } from '../transport'
import { getAudioContext, getDecodeContext, resumeAudio, audioRunning, soundAllowedWithoutTouch } from '../audio/audioContext'
import { MicCapture, MicDeniedError } from '../audio/micCapture'
import { Vad } from '../audio/vad'
import { Player, type CtxLike } from '../audio/player'
import { PromptCache } from '../audio/promptCache'
import { PreRoll, framesForMs } from '../audio/preRoll'
import { getToneBuffer, type ToneName } from '../audio/tones'
import { speakText } from '../audio/speech'
import { lastTurn, markServerMessage, markSoundStarted, markSpeechEnd } from '../audio/latency'
import { approve, abortApproval } from '../webauthn/approve'
import { enrol, hasPlatformAuthenticator } from '../webauthn/enrol'
import { env, clearOverride, writeOverride } from '../config/env'
import { flags } from '../config/flags'
import { timeouts } from '../config/timeouts'
import { vadConfig } from '../config/vad'
import { languages, CONSENT_VERSION } from '../config/languages'
import { vibrate } from '../lib/haptics'
import { formatNaira, formatTime } from '../lib/format'
import { t } from '../i18n'
import {
  language, consentId, deviceToken, onboardingComplete, theme, highContrast, clearSettings, startSettingsEffects,
} from '../lib/settings'
import type { Lang, ServerMessage } from '../protocol/messages'
import { errorText } from './account'
import { initialState, reduce, type MachineEvent, type MachineState } from './machine'

export { language, theme, highContrast, onboardingComplete, consentId, deviceToken, lastTurn, protocolLog, audioRunning }
export { flags, vadConfig, env, languages }

/* ------------------------------------------------------------------ singletons */
const transport = createTransport()
const mic = new MicCapture()
const vad = new Vad()
const prompts = new PromptCache()
const player = new Player({
  getContext: () => getAudioContext() as unknown as CtxLike,
  speakText,
})
const preRoll = new PreRoll(framesForMs(vadConfig.preSpeechPadMs + vadConfig.minSpeechMs + 100))

/* ------------------------------------------------------------------ signals */
const machine = signal<MachineState>(initialState)
export const uiState = computed(() => machine.value.ui)
export const draft = computed(() => machine.value.draft)
export const transcript = computed(() => machine.value.transcript)
export const partialTranscript = computed(() => machine.value.partial)
export const resultKind = computed(() => machine.value.result)
export const cancelKind = computed(() => machine.value.cancel)
export const errorOverlay = computed(() => machine.value.error)
export const unclearReply = computed(() => machine.value.unclear)
export const micLevel = mic.level
export const isSpeaking = player.isSpeaking
export const connection = transport.status
export const lastLatency = lastTurn
export const bankMode = signal<'mock' | 'sandbox' | 'live' | null>(null)
export const hintGrown = signal(false)
export const fingerprintRetry = signal(false)
export const fingerprintDeadline = signal(0)
export const announcement = signal('')
export const bootProgress = signal(0)
export const booted = signal(false)
export const devPanelOpen = signal(false)
export const showLatency = signal(false)
export const locked = signal(false)
export const readbackWarnings = signal<string[]>([])
export const bankSimulated = signal<boolean | null>(null)
export const duplicateNotice = signal<{ amount: string; name: string; when: string } | null>(null)
export const scamPauseUntil = signal(0)
export const updateAvailable = signal(false)
export const toast = signal<string | null>(null)
/** Where the voice asked to go ("open settings"); the app routes there and clears it. */
export const navRequest = signal<string | null>(null)
/** True while Avenza speaks a language that has not passed the native-speaker test. */
export const languageBeta = signal(false)
/** The last balance the bank gave by voice ("what is my balance"). */
export const lastBalance = signal<{ availableKobo: number; availableDisplay: string } | null>(null)

/** The last few lines of the conversation, for the chat bubbles on the home screen. Never persisted. */
export type ChatLine = { who: 'avenza' | 'you'; text: string; at: number }
export const conversation = signal<ChatLine[]>([])
export function addChat(who: ChatLine['who'], text: string): void {
  const clean = text.trim()
  if (!clean) return
  // peek(): this runs inside effects (prompt playback); reading .value there would subscribe and loop
  const current = conversation.peek()
  const last = current[current.length - 1]
  if (last && last.who === who && last.text === clean) return
  conversation.value = [...current, { who, text: clean, at: Date.now() }].slice(-6)
}
export const lastAnswerTransferId = computed(() => machine.value.transferId)

export const simulated = computed(() => bankMode.value === 'mock' || bankMode.value === 'sandbox')

/** Display-only threshold for the scam-pause warning (flag scamPause). The server decides the transfer. */
const SCAM_PAUSE_KOBO = 10_000_000
export const scamPauseActive = computed(() => {
  const d = machine.value.draft
  return flags.scamPause && machine.value.ui === 'readback' && !!d?.isNewRecipient && d.amountKobo >= SCAM_PAUSE_KOBO && scamPauseUntil.value > Date.now()
})

/* ------------------------------------------------------------------ helpers */
const localeFor = (code: string) => languages.find((l) => l.code === code)?.speechLocale ?? 'en-NG'

function showToast(msg: string) {
  toast.value = msg
  setTimeout(() => {
    if (toast.value === msg) toast.value = null
  }, 2600)
}
export const dismissToast = () => (toast.value = null)
/** Short confirmation or error message for screens. */
export const notify = showToast

function announce(text: string) {
  announcement.value = text
}

function playPrompt(id: string): Promise<void> {
  const said = prompts.textOf(id, language.value)
  if (said) addChat('avenza', said)
  if (!audioRunning.value) return Promise.resolve()
  const r = prompts.resolve(id, language.value)
  if (!r) return Promise.resolve()
  if (r.kind === 'file') {
    const buf = prompts.buffer(r.entry)
    return buf ? player.playBuffer(buf, id) : player.speak(r.entry.text, localeFor(r.entry.lang), id)
  }
  return player.speak(r.text, localeFor(r.lang), id)
}

function playTone(name: ToneName): boolean {
  if (!audioRunning.value) return false
  void player.playBuffer(getToneBuffer(getAudioContext(), name), name)
  return true
}

const timers: Record<string, ReturnType<typeof setTimeout> | undefined> = {}
function setTimer(name: string, ms: number, fn: () => void) {
  clearTimer(name)
  timers[name] = setTimeout(() => {
    timers[name] = undefined
    fn()
  }, ms)
}
function clearTimer(name: string) {
  if (timers[name]) clearTimeout(timers[name])
  timers[name] = undefined
}

/* ------------------------------------------------------------------ machine dispatch */
const benign = new Set(['SERVER_LISTENING', 'DISMISS_ERROR', 'TRANSPORT_RESTORED', 'TRANSCRIPT_PARTIAL'])

function dispatch(e: MachineEvent): void {
  const prev = machine.value
  const next = reduce(prev, e)
  if (next === prev) {
    if (!benign.has(e.type) && import.meta.env.DEV) console.debug('[avenza] ignored event', e.type, 'in', prev.ui)
    return
  }
  machine.value = next
  onChange(prev, next)
}

function statusWord(s: MachineState): string {
  switch (s.ui) {
    case 'listening': return t('status.listening')
    case 'hearing': return t('status.hearing')
    case 'checking': return t('status.checking')
    case 'readback': return t('status.readback')
    case 'fingerprint': return t('status.fingerprint')
    case 'sending': return t('status.sending')
    case 'result': return s.result === 'settled' ? t('status.settled') : s.result === 'failed' ? t('status.failed') : t('status.pending')
    case 'cancelled': return s.cancel === 'expired' ? t('status.expired') : t('status.cancelled')
  }
}

function onChange(prev: MachineState, next: MachineState): void {
  if (next.ui !== prev.ui) enterState(prev, next)
  else if (next.ui === 'result' && next.result !== prev.result) enterResult(next)
  if (next.error && next.error !== prev.error) onError(next.error.code, next.error.promptId)
  if (!next.error && prev.error) syncMic()
}

function enterState(prev: MachineState, next: MachineState): void {
  if (next.ui !== 'readback') readbackWarnings.value = []
  clearTimer('filler')
  clearTimer('sending')
  clearTimer('noSpeech')
  if (prev.ui === 'fingerprint') {
    abortApproval()
    clearTimer('fingerprint')
    fingerprintRetry.value = false
  }
  announce(`${statusWord(next)}.`)
  switch (next.ui) {
    case 'listening':
      hintGrown.value = false
      setTimer('noSpeech', timeouts.noSpeechHintMs, () => {
        if (machine.value.ui !== 'listening') return
        hintGrown.value = true
        announce(t('hint.noSpeech'))
        void playPrompt('no_speech_hint')
      })
      break
    case 'hearing':
      break
    case 'checking':
      setTimer('filler', timeouts.fillerAfterMs, () => {
        if (machine.value.ui === 'checking' && !heardFromServerSinceEnd) void playPrompt('checking_bank')
      })
      break
    case 'readback':
      vibrate('readback')
      if (flags.scamPause && next.draft?.isNewRecipient && next.draft.amountKobo >= SCAM_PAUSE_KOBO) {
        scamPauseUntil.value = Date.now() + 10_000
        announce(t('scam.title'))
        void playPrompt('scam_pause')
        setTimer('scam', 10_000, () => {
          scamPauseUntil.value = 0
        })
      }
      break
    case 'fingerprint':
      vibrate('fingerprint')
      break
    case 'sending':
      setTimer('sending', timeouts.sendingFillerAfterMs, () => {
        if (machine.value.ui === 'sending' && !serverVoices()) void playPrompt('sending')
      })
      break
    case 'result':
      enterResult(next)
      break
    case 'cancelled':
      vibrate('failed')
      player.stop()
      if (!serverVoices()) void playPrompt(next.cancel === 'expired' ? 'expired' : 'cancelled')
      scheduleReturn(timeouts.cancelledReturnMs)
      break
  }
  syncMic()
}

function enterResult(s: MachineState): void {
  player.stop()
  announce(`${statusWord(s)}.`)
  if (s.result === 'settled') {
    vibrate('settled')
    playTone('tone_success')
    if (!serverVoices()) void playPrompt('settled')
    scheduleReturn(timeouts.resultReturnMs)
  } else if (s.result === 'failed') {
    vibrate('failed')
    playTone('tone_error')
    if (!serverVoices()) void playPrompt('failed')
    scheduleReturn(timeouts.resultReturnMs)
  } else {
    clearTimer('return')
    returnWaiting = null
    if (!serverVoices()) void playPrompt('pending_unknown')
  }
}

function onError(code: string, promptId: string): void {
  vibrate('failed')
  closeMic()
  player.stop()
  playTone('tone_error')
  if (!serverVoices()) void playPrompt(promptId)
  announce(prompts.textOf(promptId, language.value) ?? t(`error.${code}`))
}

/* ------------------------------------------------------------------ returning to listening */
let returnWaiting: number | null = null

function scheduleReturn(ms: number): void {
  returnWaiting = ms
  clearTimer('return')
  // never stall if audio never plays (e.g. blocked autoplay)
  setTimer('returnHard', ms + 8000, goBackToListening)
  if (player.idle) startReturnTimer()
}

function startReturnTimer(): void {
  if (returnWaiting == null) return
  const ms = returnWaiting
  returnWaiting = null
  setTimer('return', ms, goBackToListening)
}

function goBackToListening(): void {
  clearTimer('return')
  clearTimer('returnHard')
  returnWaiting = null
  dispatch({ type: 'RETURN_TO_LISTENING' })
  if (machine.value.ui === 'listening') armMic()
}

/* ------------------------------------------------------------------ microphone / half-duplex */
let started = false
let micArmed = false
let toneQueued = false
let welcomed = false
let micOpen = false
let streaming = false
let heardFromServerSinceEnd = false
let readbackPromptTimer = false

function wantsMic(): boolean {
  const m = machine.value
  return started && micArmed && (m.ui === 'listening' || m.ui === 'readback') && !m.error && !scamPauseActive.value
}

function syncMic(): void {
  if (streaming) return // never cut an utterance in progress
  if (!wantsMic() || player.isSpeaking.value) {
    closeMic()
    return
  }
  if (!toneQueued) {
    toneQueued = true
    vibrate('listening')
    if (playTone('tone_listening')) return // reopens on idle
  }
  openMic()
}

function openMic(): void {
  if (micOpen || !mic.stream) return
  micOpen = true
  mic.gate = true
  preRoll.clear()
  void vad.resume()
}

function closeMic(): void {
  if (!micOpen) return
  micOpen = false
  mic.gate = false
  streaming = false
  preRoll.clear()
  void vad.pause()
}

function armMic(): void {
  micArmed = true
  toneQueued = false
  if (!welcomed) {
    welcomed = true
    if (!serverVoices()) void playPrompt('listening')
  }
  syncMic()
}

player.onIdle(() => {
  syncMic()
  if (returnWaiting != null) startReturnTimer()
  // read-back finished and the server did not send `listening`: say the options ourselves
  if (machine.value.ui === 'readback' && !micArmed && !readbackPromptTimer) {
    readbackPromptTimer = true
    setTimeout(() => {
      readbackPromptTimer = false
      if (machine.value.ui === 'readback' && !micArmed && player.idle) {
        void playPrompt('say_yes_no_repeat')
        micArmed = true
        toneQueued = false
        syncMic()
      }
    }, 700)
  }
})
player.onSoundStart(() => markSoundStarted())

/* ------------------------------------------------------------------ utterances */
function onSpeechStart(): void {
  if (!micOpen || streaming) return
  streaming = true
  micArmed = false
  clearTimer('noSpeech')
  dispatch({ type: 'VAD_START' })
  transport.send({ type: 'utterance.start', sampleRate: 16000 })
  for (const f of preRoll.drain()) transport.sendAudio(f)
}

function onSpeechEnd(): void {
  if (!streaming) return
  streaming = false
  transport.send({ type: 'utterance.end' })
  markSpeechEnd()
  heardFromServerSinceEnd = false
  dispatch({ type: 'VAD_END' })
  closeMic()
  waitForServer()
  if (machine.value.ui === 'readback') {
    setTimer('filler', timeouts.fillerAfterMs, () => {
      if (!heardFromServerSinceEnd) void playPrompt('checking_bank')
    })
  }
}

/** Every client wait has a timeout. When it fires: speak, tell the user money has not moved, never guess. */
function waitForServer(): void {
  setTimer('reply', timeouts.serverReplyMs, () => {
    dispatch({ type: 'SERVER_ERROR', code: 'timeout', promptId: 'err_generic' })
  })
}

/* ------------------------------------------------------------------ server messages */
/** True when the backend supplies every spoken prompt (live). In mock mode the app speaks its own cached prompts. */
const serverVoices = () => env.BACKEND_MODE === 'live'

function speakServerText(text: string): void {
  addChat('avenza', text)
  announce(text)
  if (audioRunning.value) void player.speak(text, localeFor(language.value), 'server-speech')
}

async function playClip(msg: Extract<ServerMessage, { type: 'prompt.play' }>): Promise<void> {
  if (msg.promptId) {
    void playPrompt(msg.promptId)
    return
  }
  if (msg.warnings) readbackWarnings.value = msg.warnings
  if (msg.text) addChat('avenza', msg.text)
  if (msg.audio) {
    // server-synthesised speech, in order with everything else
    if (msg.text) announce(msg.text)
    if (audioRunning.value) player.pushPcm(msg.audio.pcm, msg.audio.sampleRate, true)
    return
  }
  const url = msg.clipUrl ?? msg.audioUrl
  if (!url) {
    if (msg.text) speakServerText(msg.text)
    return
  }
  if (url.startsWith('speak:')) {
    // mock-only convention: speak this text
    speakServerText(url.slice(6))
    return
  }
  try {
    const res = await fetch(/^https?:/.test(url) ? url : `${env.API_BASE_URL}${url}`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const buf = await getAudioContext().decodeAudioData(await res.arrayBuffer())
    if (msg.text) announce(msg.text)
    if (audioRunning.value) void player.playBuffer(buf, 'clip')
  } catch (e) {
    console.warn('[avenza] could not play clip', e)
    if (msg.text) speakServerText(msg.text) // the device voice is the fallback
  }
}

function onServer(msg: ServerMessage): void {
  markServerMessage(msg.type)
  heardFromServerSinceEnd = true
  clearTimer('reply')
  clearTimer('filler')
  switch (msg.type) {
    case 'transcript.partial':
      dispatch({ type: 'TRANSCRIPT_PARTIAL', text: msg.text })
      break
    case 'transcript.final':
      addChat('you', msg.text)
      dispatch({ type: 'TRANSCRIPT_FINAL', text: msg.text })
      break
    case 'prompt.play':
      void playClip(msg)
      break
    case 'audio.stream':
      break // header only; PCM arrives via onAudio
    case 'approval.request':
      onApprovalRequest(msg)
      break
    case 'state.changed':
      dispatch({ type: 'STATE_CHANGED', transferId: msg.transferId, state: msg.state, draft: msg.draft })
      break
    case 'listening':
      dispatch({ type: 'SERVER_LISTENING' })
      armMic()
      break
    case 'error':
      if (msg.code === 'device_not_enrolled' || msg.code === 'consent_required') {
        handleUnauthorized()
        break
      }
      if (msg.code === 'transfers_locked') locked.value = true
      if (msg.code.startsWith('unclear')) {
        player.stop()
        if (!serverVoices()) void playPrompt(msg.promptId)
        announce(t('hint.unclear'))
      }
      dispatch({ type: 'SERVER_ERROR', code: msg.code, promptId: msg.promptId })
      break
    case 'session.ready':
      bankSimulated.value = msg.bankSimulated
      break
    case 'lock.changed':
      locked.value = msg.locked
      break
    case 'navigate':
      // "open settings", "show my transactions", "go home": the app follows the voice
      navRequest.value = msg.screen === 'home' ? '/' : `/${msg.screen}`
      break
    case 'language.changed':
      // Avenza heard (or was asked for) another language: the screen follows it too
      if ((['en', 'yo', 'ha', 'ig'] as const).includes(msg.language as Lang)) language.value = msg.language as Lang
      languageBeta.value = msg.beta
      break
    case 'balance':
      lastBalance.value = { availableKobo: msg.availableKobo, availableDisplay: msg.availableDisplay ?? formatNaira(msg.availableKobo) }
      break
  }
}

/* ------------------------------------------------------------------ fingerprint */
let approvalSeq = 0
let attempts = 0
const approvalSent = new Set<number>()
let currentRequest: { transferId: string; options: Extract<ServerMessage, { type: 'approval.request' }>['options'] } | null = null

function onApprovalRequest(msg: Extract<ServerMessage, { type: 'approval.request' }>): void {
  dispatch({ type: 'APPROVAL_REQUEST', transferId: msg.transferId })
  if (machine.value.ui !== 'fingerprint') return
  const seq = ++approvalSeq
  attempts = 0
  currentRequest = { transferId: msg.transferId, options: msg.options }
  fingerprintRetry.value = false
  fingerprintDeadline.value = Date.now() + timeouts.fingerprintMs
  setTimer('fingerprint', timeouts.fingerprintMs, () => cancelFingerprint('expired'))
  if (!serverVoices()) void playPrompt('place_finger_approve')
  void attempt(seq)
}

async function attempt(seq: number): Promise<void> {
  if (!currentRequest) return
  const { transferId, options } = currentRequest
  const res = await approve(options)
  if (seq !== approvalSeq || machine.value.ui !== 'fingerprint') return // stale
  if (res.ok) {
    if (approvalSent.has(seq)) return // exactly once per approval.request
    approvalSent.add(seq)
    transport.send({ type: 'approval.response', transferId, assertion: res.assertion })
    return
  }
  if (res.reason === 'aborted') return
  attempts++
  if (attempts === 1) {
    fingerprintRetry.value = true
    vibrate('failed')
    void playPrompt('fingerprint_retry')
    announce(prompts.textOf('fingerprint_retry', language.value) ?? '')
  } else {
    cancelFingerprint('cancelled')
  }
}

function cancelFingerprint(kind: 'cancelled' | 'expired'): void {
  if (machine.value.ui !== 'fingerprint') return
  const transferId = machine.value.transferId
  abortApproval()
  clearTimer('fingerprint')
  dispatch({ type: 'LOCAL_CANCEL', kind })
  // tell the server the customer did not approve (needs backend agreement)
  if (transferId) transport.send({ type: 'confirm.response', transferId, answer: 'no' })
}

/* ------------------------------------------------------------------ actions for screens */
export function confirm(answer: 'yes' | 'no' | 'repeat'): void {
  const m = machine.value
  if (m.ui !== 'readback' || !m.transferId || scamPauseActive.value && answer === 'yes') return
  player.stop()
  closeMic()
  micArmed = false
  transport.send({ type: 'confirm.response', transferId: m.transferId, answer })
  heardFromServerSinceEnd = false
  waitForServer()
}

export function cancel(): void {
  if (machine.value.ui === 'fingerprint') cancelFingerprint('cancelled')
  else if (machine.value.ui === 'readback') confirm('no')
}

export function retryFingerprint(): void {
  if (!fingerprintRetry.value || machine.value.ui !== 'fingerprint') return
  fingerprintRetry.value = false
  void attempt(approvalSeq)
}

export function dismissResult(): void {
  player.stop()
  goBackToListening()
}

export function dismissError(): void {
  const e = machine.value.error
  if (!e) return
  dispatch({ type: 'DISMISS_ERROR' })
  if (e.code === 'timeout' || e.code === 'provider_down') armMic()
}

export async function shareReceipt(): Promise<boolean> {
  const d = machine.value.draft
  if (!d) return false
  const text = [
    t('voice.receiptTitle'),
    `${t('voice.resultAmount')}: ${formatNaira(d.amountKobo)}`,
    `${t('voice.resultTo')}: ${d.recipientName}`,
    `${t('voice.resultBank')}: ${d.bankName} ${d.accountMasked}`,
    d.reference ? `${t('voice.resultRef')}: ${d.reference}` : '',
    `${t('voice.resultTime')}: ${formatTime(new Date())}`,
  ]
    .filter(Boolean)
    .join('\n')
  try {
    if (navigator.share) {
      await navigator.share({ title: t('voice.receiptTitle'), text })
      return true
    }
    await navigator.clipboard.writeText(text)
    showToast(t('common.copied'))
    return true
  } catch {
    return false
  }
}

/** Say something in the device voice and show it as Avenza's bubble (quick actions on the home screen). */
export function sayLocally(text: string): void {
  addChat('avenza', text)
  announce(text)
  if (audioRunning.value) void player.speak(text, localeFor(language.value), 'local')
}

export async function copyReference(): Promise<void> {
  const ref = machine.value.draft?.reference
  if (!ref) return
  try {
    await navigator.clipboard.writeText(ref)
    showToast(t('toast.copied'))
  } catch {
    /* clipboard unavailable */
  }
}

/* ------------------------------------------------------------------ voice screen lifecycle */
export async function startVoice(): Promise<void> {
  if (started) {
    syncMic()
    return
  }
  try {
    await mic.start()
  } catch (e) {
    if (e instanceof MicDeniedError) {
      dispatch({ type: 'MIC_DENIED' })
      return
    }
    throw e
  }
  if (machine.value.error?.code === 'mic_denied') dispatch({ type: 'DISMISS_ERROR' })
  mic.onFrame((frame) => {
    if (!micOpen) return
    if (streaming) transport.sendAudio(frame)
    else preRoll.push(frame)
  })
  await vad.load(async () => mic.stream as MediaStream, { onSpeechStart, onSpeechEnd })
  started = true
  sendSessionStart()
}

function sendSessionStart(): void {
  if (!deviceToken.value || !consentId.value) return
  transport.send({ type: 'session.start', deviceToken: deviceToken.value, consentId: consentId.value, language: language.value })
}

export function stopVoice(): void {
  closeMic()
  micArmed = false
  clearTimer('noSpeech')
}

/* ------------------------------------------------------------------ boot */
let initialised = false
let wasOpen = false

function initOnce(): void {
  if (initialised) return
  initialised = true
  startSettingsEffects()
  setUnauthorizedHandler(handleUnauthorized)
  transport.on(onServer)
  transport.onAudio((c) => {
    heardFromServerSinceEnd = true
    clearTimer('reply')
    player.pushPcm(c.pcm, c.sampleRate, c.final)
  })
  effect(() => {
    const s = transport.status.value
    if (s === 'open') {
      if (wasOpen && machine.value.error?.code === 'connection_lost') dispatch({ type: 'TRANSPORT_RESTORED' })
      if (wasOpen && started) sendSessionStart()
      wasOpen = true
    } else if ((s === 'reconnecting' || s === 'closed') && wasOpen) {
      if (machine.value.error?.code !== 'connection_lost' && s === 'reconnecting') dispatch({ type: 'TRANSPORT_LOST' })
    }
  })
  window.addEventListener('offline', () => {
    if (env.BACKEND_MODE === 'live') dispatch({ type: 'SERVER_ERROR', code: 'offline', promptId: 'err_offline' })
  })
  window.addEventListener('online', () => {
    if (machine.value.error?.code === 'offline') dispatch({ type: 'DISMISS_ERROR' })
  })
}

/** Start loading the Silero model + WASM (about 16 MB) in the background. Called as soon as boot hands over to the first screen. */
export function preloadVad(): void {
  void vad.load(async () => mic.stream as MediaStream, { onSpeechStart, onSpeechEnd }).catch((e) => console.warn('[avenza] VAD load failed, will retry', e))
}

export interface BootResult {
  needsTap: boolean
}

export async function boot(): Promise<BootResult> {
  initOnce()
  bootProgress.value = 0.05
  const steps: Array<Promise<unknown>> = []
  let done = 0
  const total = 4
  const track = <T>(p: Promise<T>) => {
    const w = p.finally(() => {
      done++
      bootProgress.value = 0.05 + (done / total) * 0.95
    })
    steps.push(w)
    return w
  }
  // No AudioContext before a touch (the browser warns); decode clips on an offline context instead.
  const ctx = getDecodeContext()
  await Promise.all([
    track(document.fonts?.ready ?? Promise.resolve()),
    track(prompts.load(ctx, language.value)),
    track(
      api
        .health()
        .then((h) => {
          bankMode.value = h.bankMode as 'mock' | 'sandbox' | 'live'
          bankSimulated.value = h.bankSimulated
        })
        .catch(() => {
          bankMode.value = null
        }),
    ),
    track(transport.connect().catch((e) => console.warn('[avenza] transport connect failed', e))),
  ])
  bootProgress.value = 1
  booted.value = true
  if (env.BACKEND_MODE === 'live' && deviceToken.value) {
    api.lockStatus().then((v) => (locked.value = v)).catch(() => undefined)
  }
  if (env.BACKEND_MODE === 'live' && !navigator.onLine) dispatch({ type: 'SERVER_ERROR', code: 'offline', promptId: 'err_offline' })
  return { needsTap: !audioRunning.value }
}

/** Call from a user gesture ("Tap anywhere to start", consent "I agree"). */
export async function unlockAudio(): Promise<boolean> {
  return resumeAudio()
}

/** Start sound without a touch only when the browser allows it; never create a context it would refuse. */
export async function tryStartSoundWithoutTouch(): Promise<boolean> {
  if (!soundAllowedWithoutTouch()) return false
  return resumeAudio()
}

export async function retryConnection(): Promise<void> {
  dispatch({ type: 'DISMISS_ERROR' })
  try {
    await transport.connect()
  } catch {
    dispatch({ type: 'SERVER_ERROR', code: 'offline', promptId: 'err_offline' })
  }
}

/* ------------------------------------------------------------------ onboarding */
export async function chooseLanguage(code: Lang): Promise<void> {
  language.value = code
  const info = languages.find((l) => l.code === code)
  if (info) {
    await resumeAudio()
    void player.speak(info.name, info.speechLocale, 'language-name')
  }
  void prompts.load(getDecodeContext(), code).catch(() => undefined)
}

export function speakConsent(): Promise<void> {
  player.stop()
  return playPrompt('consent_read')
}

/** Speak one line in the device voice (onboarding: no server session yet). Resolves when it has been said. */
export function speakLine(text: string): Promise<void> {
  if (!audioRunning.value) return Promise.resolve()
  return player.speak(text, localeFor(language.value), 'onboarding')
}

/** The browser locale for spoken answers in the current language. */
export const answerLocale = () => localeFor(language.value)

export function stopSpeaking(): void {
  player.stop()
}

export async function giveConsent(): Promise<'ok' | 'mic-denied' | 'error'> {
  await resumeAudio() // the tap unlocks audio
  try {
    await mic.start()
  } catch (e) {
    if (e instanceof MicDeniedError) {
      dispatch({ type: 'MIC_DENIED' })
      void playPrompt('err_mic_denied')
      return 'mic-denied'
    }
    return 'error'
  }
  player.stop()
  return 'ok' // the consent is recorded with the backend right after the fingerprint is registered (it needs the device token)
}

export async function retryMic(): Promise<boolean> {
  try {
    await mic.start()
    dispatch({ type: 'DISMISS_ERROR' })
    return true
  } catch {
    return false
  }
}

export type EnrolOutcome = 'ok' | 'cancelled' | 'no-authenticator' | 'already-registered' | 'name-required' | 'error'

/** The backend's own message for the last failed enrolment step, for the setup screen to show. */
export const enrolError = signal('')

async function recordConsent(): Promise<void> {
  const c = await api.createConsent({ wordingVersion: CONSENT_VERSION, language: language.value })
  consentId.value = c.consentId
}

/**
 * Register the fingerprint (a passkey on this device), then record the consent the customer gave on the previous
 * screen. The backend needs the device token for the consent, so the order is passkey first, consent second.
 */
export async function registerFingerprint(displayName = '', opts: { quiet?: boolean } = {}): Promise<EnrolOutcome> {
  enrolError.value = ''
  const name = displayName.trim()
  const existing = !!deviceToken.value
  if (!existing && (name.length < 1 || name.length > 200)) return 'name-required'
  try {
    if (existing && !consentId.value) {
      await recordConsent() // an earlier attempt registered the passkey but not the consent
      onboardingComplete.value = true
      return 'ok'
    }
    if (!opts.quiet) void playPrompt('place_finger_enrol') // the onboarding conversation says it itself
    const owner = existing ? await api.me() : null
    const start = await api.registerOptions({ displayName: name, language: language.value, existing: owner ? { userId: owner.id, deviceToken: deviceToken.value as string } : undefined })
    const res = await enrol(start.options)
    if (!res.ok) {
      if (res.reason === 'error') {
        enrolError.value = res.detail === 'address' ? t('finger.addressMismatch') : t('finger.errorDetail', { detail: res.detail ?? '' })
      }
      return res.reason
    }
    const v = await api.registerVerify({ challengeId: start.challengeId, credential: res.credential })
    deviceToken.value = v.deviceToken
    if (!consentId.value) await recordConsent()
    onboardingComplete.value = true
    playTone('tone_success')
    return 'ok'
  } catch (e) {
    enrolError.value = errorText(e)
    return 'error'
  }
}

export { hasPlatformAuthenticator }

export function finishOnboardingWithoutFingerprint(): void {
  onboardingComplete.value = true
}

export function withdrawConsent(): void {
  stopVoice()
  mic.stop()
  started = false
  player.stop()
  clearSettings()
  clearOverride()
  dispatch({ type: 'RETURN_TO_LISTENING' })
}

/* ------------------------------------------------------------------ stubs: lock / duplicate */
export async function lockTransfers(): Promise<void> {
  try {
    await api.lock()
  } catch (e) {
    showToast(errorText(e))
    return
  }
  locked.value = true
  stopVoice()
  if (!serverVoices()) void playPrompt('locked')
  else announce(t('lock.title'))
}

/** Unlocking needs the fingerprint: the backend issues a challenge and verifies the assertion. */
export async function unlockTransfers(): Promise<boolean> {
  try {
    const challenge = await api.unlockOptions()
    const res = await approve(challenge.options)
    if (!res.ok) return false
    await api.unlockVerify({ challengeId: challenge.challengeId, credential: res.assertion })
    locked.value = false
    return true
  } catch (e) {
    showToast(errorText(e))
    return false
  }
}

/** The backend no longer knows this device (401): forget it and enrol again. */
function handleUnauthorized(): void {
  if (!deviceToken.value) return
  stopVoice()
  transport.close()
  deviceToken.value = null
  consentId.value = null
  onboardingComplete.value = false
  started = false
  showToast(t('error.deviceExpired'))
  setTimeout(() => location.assign('/onboarding/language'), 1200)
}

export function showDuplicateNotice(): void {
  duplicateNotice.value = { amount: '₦5,000.00', name: 'Aisha Bello', when: '2 minutes ago' }
  void playPrompt('duplicate_warning')
}
export const dismissDuplicate = () => (duplicateNotice.value = null)

/* ------------------------------------------------------------------ dev panel */
export function devSetBackend(mode: 'mock' | 'live'): void {
  writeOverride({ BACKEND_MODE: mode })
  location.reload()
}

export function devRunScenario(id: string): void {
  writeOverride({ MOCK_SCENARIO: id })
  const tr = transport as unknown as { setScenario?: (id: string) => void }
  if (tr.setScenario) {
    player.stop()
    closeMic()
    machine.value = initialState
    micArmed = false
    tr.setScenario(id)
    sendSessionStart()
    goBackToListening()
  } else {
    location.reload()
  }
}

export function devApplyVad(): void {
  vad.applyConfig()
}

export function devClearData(): void {
  withdrawConsent()
  location.assign('/boot')
}

export function devClearOverride(): void {
  clearOverride()
  location.reload()
}

export function notifyUpdateAvailable(): void {
  updateAvailable.value = true
}

export { scenarioIds, scenarios } from '../mocks/scenarios'
export { protocolLog as devProtocolLog }

if (import.meta.env.DEV) {
  ;(window as unknown as Record<string, unknown>).__avenza = {
    get debug() {
      return { micOpen, micArmed, toneQueued, started, streaming, speaking: player.isSpeaking.value, audio: audioRunning.value, ui: machine.value.ui, level: mic.level.value, gate: mic.gate }
    },
  }
}
