import { z } from 'zod'
import type { AudioChunk, ClientMessage, ServerMessage, TransferDraft } from './messages'
import { transferStates } from './schemas'

/**
 * The live backend's WebSocket format (docs/PROTOCOL.md in the backend repo): snake_case JSON.
 * This file is the only place that knows those field names; the rest of the app uses the internal
 * camelCase ServerMessage / ClientMessage types.
 */

/* ------------------------------------------------------------------ client -> server */
export function encodeClientMessage(msg: ClientMessage): Record<string, unknown> {
  switch (msg.type) {
    case 'session.start':
      return { type: 'session.start', device_token: msg.deviceToken, consent_id: msg.consentId, language: msg.language }
    case 'utterance.start':
      return { type: 'utterance.start', sample_rate: msg.sampleRate }
    case 'utterance.end':
      return { type: 'utterance.end' }
    case 'approval.response':
      return { type: 'approval.response', credential: msg.assertion }
    case 'confirm.response':
      // The backend has no button message: a tapped answer is the same as saying it (typed utterance).
      return { type: 'utterance.text', text: msg.answer, final: true }
  }
}

/* ------------------------------------------------------------------ server -> client */
const summary = z.looseObject({
  id: z.string().nullable().optional(),
  amount_kobo: z.number().optional(),
  bank_name: z.string().nullable().optional(),
  account_last4: z.string().optional(),
  recipient: z.string().nullable().optional(),
  reference: z.string().nullable().optional(),
  risk_flags: z.array(z.string()).optional(),
  failure_reason: z.string().nullable().optional(),
})
type Summary = z.infer<typeof summary>

const wire = z.discriminatedUnion('type', [
  z.looseObject({ type: z.literal('transcript.partial'), text: z.string() }),
  z.looseObject({ type: z.literal('transcript.final'), text: z.string() }),
  z.looseObject({
    type: z.literal('prompt.play'),
    id: z.string().optional(),
    text: z.string().optional(),
    audio_url: z.string().nullable().optional(),
    audio: z.looseObject({ sample_rate: z.number(), data: z.string() }).nullable().optional(),
    warnings: z.array(z.string()).optional(),
  }),
  z.looseObject({ type: z.literal('audio.stream'), data: z.string(), sample_rate: z.number().positive() }),
  z.looseObject({
    type: z.literal('approval.request'),
    transfer_id: z.string(),
    options: z.looseObject({}),
    transfer: summary.optional(),
  }),
  z.looseObject({
    type: z.literal('state.changed'),
    transfer_id: z.string(),
    state: z.enum(transferStates),
    amount_display: z.string().nullable().optional(),
    recipient: z.string().nullable().optional(),
    reference: z.string().nullable().optional(),
  }),
  z.looseObject({ type: z.literal('listening') }),
  z.looseObject({ type: z.literal('error'), code: z.string(), prompt_id: z.string().optional(), message: z.string().optional() }),
  z.looseObject({
    type: z.literal('session.ready'),
    language: z.string(),
    language_verified: z.boolean().optional(),
    bank: z.looseObject({ simulated: z.boolean() }),
    approval_ttl_s: z.number().optional(),
  }),
  z.looseObject({ type: z.literal('lock.changed'), locked: z.boolean() }),
])

const known = new Set(wire.options.map((o) => o.shape.type.value as string))

export type WireParse =
  | { ok: true; msg: ServerMessage; audio?: AudioChunk }
  | { ok: false; reason: 'unknown-type' | 'malformed'; detail?: string }

export function parseNairaToKobo(display: string | null | undefined): number | null {
  if (!display) return null
  const digits = display.replace(/[^0-9.]/g, '')
  const n = Number(digits)
  return Number.isFinite(n) && digits !== '' ? Math.round(n * 100) : null
}

const NEW_RECIPIENT_FLAGS = new Set(['new_recipient_large', 'new_recipient'])

/** Draft shown on the read-back screen, from the backend's transfer summary. */
export function draftFromSummary(s: Summary): TransferDraft {
  return {
    amountKobo: s.amount_kobo ?? 0,
    recipientName: s.recipient ?? '',
    bankName: s.bank_name ?? '',
    accountMasked: s.account_last4 ? `•••• ${s.account_last4}` : '',
    reference: s.reference ?? undefined,
    failureReason: s.failure_reason ?? undefined,
    isNewRecipient: (s.risk_flags ?? []).some((f) => NEW_RECIPIENT_FLAGS.has(f)),
  }
}

export function decodePcm(base64: string): Int16Array {
  const bin = atob(base64)
  const even = bin.length - (bin.length % 2)
  const bytes = new Uint8Array(even)
  for (let i = 0; i < even; i++) bytes[i] = bin.charCodeAt(i)
  return new Int16Array(bytes.buffer)
}

/** Never throws. Unknown message types are ignored; malformed ones are reported and dropped. */
export function parseWireMessage(raw: unknown): WireParse {
  let data: unknown = raw
  if (typeof raw === 'string') {
    try {
      data = JSON.parse(raw)
    } catch {
      return { ok: false, reason: 'malformed', detail: 'invalid JSON' }
    }
  }
  const type = (data as { type?: unknown } | null)?.type
  if (typeof type !== 'string') return { ok: false, reason: 'malformed', detail: 'no type' }
  if (!known.has(type)) return { ok: false, reason: 'unknown-type' }
  const r = wire.safeParse(data)
  if (!r.success) return { ok: false, reason: 'malformed', detail: r.error.message }
  const m = r.data
  switch (m.type) {
    case 'transcript.partial':
    case 'transcript.final':
      return { ok: true, msg: { type: m.type, text: m.text } }
    case 'prompt.play':
      return {
        ok: true,
        msg: {
          type: 'prompt.play',
          text: m.text,
          audioUrl: m.audio_url ?? undefined,
          audio: m.audio ? { sampleRate: m.audio.sample_rate, pcm: decodePcm(m.audio.data) } : undefined,
          warnings: m.warnings,
        },
      }
    case 'audio.stream':
      return {
        ok: true,
        msg: { type: 'audio.stream', sampleRate: m.sample_rate, final: true },
        audio: { pcm: decodePcm(m.data), sampleRate: m.sample_rate, final: true },
      }
    case 'approval.request': {
      const opts = m.options as { publicKey?: unknown }
      const options = (opts.publicKey ?? m.options) as { challenge?: unknown }
      if (typeof options.challenge !== 'string') return { ok: false, reason: 'malformed', detail: 'approval options without challenge' }
      return {
        ok: true,
        msg: {
          type: 'approval.request',
          transferId: m.transfer_id,
          options: options as never,
          draft: m.transfer ? draftFromSummary(m.transfer) : undefined,
        },
      }
    }
    case 'state.changed': {
      const kobo = parseNairaToKobo(m.amount_display)
      const draft: TransferDraft | undefined =
        kobo != null
          ? { amountKobo: kobo, recipientName: m.recipient ?? '', bankName: '', accountMasked: '', reference: m.reference ?? undefined }
          : undefined
      return { ok: true, msg: { type: 'state.changed', transferId: m.transfer_id, state: m.state, draft } }
    }
    case 'listening':
      return { ok: true, msg: { type: 'listening' } }
    case 'error':
      return { ok: true, msg: { type: 'error', code: m.code, promptId: m.prompt_id ?? 'error_generic', message: m.message } }
    case 'session.ready':
      return {
        ok: true,
        msg: {
          type: 'session.ready',
          language: m.language,
          languageVerified: m.language_verified ?? true,
          bankSimulated: m.bank.simulated,
          approvalTtlS: m.approval_ttl_s ?? null,
        },
      }
    case 'lock.changed':
      return { ok: true, msg: { type: 'lock.changed', locked: m.locked } }
  }
}
