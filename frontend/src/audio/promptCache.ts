import { z } from 'zod'
import type { Lang } from '../protocol/messages'

const manifestSchema = z.object({
  version: z.number(),
  voice: z.string(),
  prompts: z.array(
    z.object({
      id: z.string(),
      lang: z.string(),
      file: z.string().optional(), // placeholder manifests have no audio yet
      text: z.string(),
    }),
  ),
})
export type PromptManifest = z.infer<typeof manifestSchema>
export type PromptEntry = PromptManifest['prompts'][number]

export type Resolved = { kind: 'file'; entry: PromptEntry & { file: string } } | { kind: 'text'; text: string; lang: string } | null

/**
 * Looks up `id` for `lang`, falls back to English, and when no audio file exists
 * returns the manifest text so the caller can speak it with speechSynthesis.
 */
export function resolvePrompt(
  manifest: PromptManifest | null,
  id: string,
  lang: Lang,
  hasBuffer: (entry: PromptEntry) => boolean = () => true,
): Resolved {
  if (!manifest) return null
  const find = (l: string) => manifest.prompts.find((p) => p.id === id && p.lang === l)
  const candidates = [find(lang), lang === 'en' ? undefined : find('en')].filter((e): e is PromptEntry => !!e)
  for (const e of candidates) {
    if (e.file && hasBuffer(e)) return { kind: 'file', entry: e as PromptEntry & { file: string } }
  }
  const e = candidates[0]
  return e ? { kind: 'text', text: e.text, lang: e.lang } : null
}

export class PromptCache {
  manifest: PromptManifest | null = null
  private buffers = new Map<string, AudioBuffer>() // key: lang/id

  private key(e: PromptEntry) {
    return `${e.lang}/${e.id}`
  }

  /** Fetch the manifest and decode every clip for `lang` (and English as fallback). */
  async load(ctx: BaseAudioContext, lang: Lang): Promise<void> {
    const res = await fetch('/prompts/manifest.json', { cache: 'no-cache' })
    if (!res.ok) throw new Error(`prompt manifest ${res.status}`)
    this.manifest = manifestSchema.parse(await res.json())
    const wanted = this.manifest.prompts.filter((p) => p.file && (p.lang === lang || p.lang === 'en'))
    await Promise.all(
      wanted.map(async (p) => {
        try {
          const r = await fetch(`/prompts/${p.file}`)
          if (!r.ok) return
          const buf = await ctx.decodeAudioData(await r.arrayBuffer())
          this.buffers.set(this.key(p), buf)
        } catch {
          /* missing or undecodable: falls back to speech */
        }
      }),
    )
  }

  resolve(id: string, lang: Lang): Resolved {
    return resolvePrompt(this.manifest, id, lang, (e) => this.buffers.has(this.key(e)))
  }

  buffer(entry: PromptEntry): AudioBuffer | undefined {
    return this.buffers.get(this.key(entry))
  }

  /** Text of a prompt, for the screen reader / live region. */
  textOf(id: string, lang: Lang): string | null {
    const r = this.resolve(id, lang)
    if (!r) return null
    return r.kind === 'text' ? r.text : r.entry.text
  }
}
