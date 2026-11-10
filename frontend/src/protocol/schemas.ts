import { z } from 'zod'
import type { ServerMessage } from './messages'

export const transferStates = [
  'DRAFTED',
  'READBACK_PLAYED',
  'CONFIRMED_BY_VOICE',
  'AWAITING_BIOMETRIC',
  'APPROVED',
  'SUBMITTED',
  'SETTLED',
  'FAILED',
  'PENDING_UNKNOWN',
  'CANCELLED',
  'EXPIRED',
] as const

export const draftSchema = z.object({
  amountKobo: z.number().int().nonnegative(),
  recipientName: z.string(),
  bankName: z.string(),
  accountMasked: z.string(),
  reference: z.string().optional(),
  failureReason: z.string().optional(),
  isNewRecipient: z.boolean().optional(),
})

const options = z.looseObject({ challenge: z.string() })

export const serverMessageSchema = z.discriminatedUnion('type', [
  z.object({ type: z.literal('transcript.partial'), text: z.string() }),
  z.object({ type: z.literal('transcript.final'), text: z.string() }),
  z.object({ type: z.literal('prompt.play'), promptId: z.string().optional(), clipUrl: z.string().optional() }),
  z.object({ type: z.literal('audio.stream'), sampleRate: z.number().positive(), final: z.boolean() }),
  z.object({ type: z.literal('approval.request'), transferId: z.string(), options }),
  z.object({
    type: z.literal('state.changed'),
    transferId: z.string(),
    state: z.enum(transferStates),
    draft: draftSchema.optional(),
  }),
  z.object({ type: z.literal('listening') }),
  z.object({ type: z.literal('error'), code: z.string(), promptId: z.string() }),
])

const knownTypes = new Set<string>([
  'transcript.partial',
  'transcript.final',
  'prompt.play',
  'audio.stream',
  'approval.request',
  'state.changed',
  'listening',
  'error',
])

export type ParseResult =
  | { ok: true; msg: ServerMessage }
  | { ok: false; reason: 'unknown-type' | 'malformed'; detail?: string }

/** Unknown types are ignored; malformed messages are logged and dropped. Never throws. */
export function parseServerMessage(raw: unknown): ParseResult {
  let data: unknown = raw
  if (typeof raw === 'string') {
    try {
      data = JSON.parse(raw)
    } catch {
      return { ok: false, reason: 'malformed', detail: 'invalid JSON' }
    }
  }
  if (typeof data !== 'object' || data === null || typeof (data as { type?: unknown }).type !== 'string') {
    return { ok: false, reason: 'malformed', detail: 'no type' }
  }
  if (!knownTypes.has((data as { type: string }).type)) return { ok: false, reason: 'unknown-type' }
  const r = serverMessageSchema.safeParse(data)
  if (!r.success) return { ok: false, reason: 'malformed', detail: r.error.message }
  return { ok: true, msg: r.data as ServerMessage }
}
