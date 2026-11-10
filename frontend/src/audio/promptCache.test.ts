import { describe, expect, it } from 'vitest'
import { resolvePrompt, type PromptManifest } from './promptCache'

const manifest: PromptManifest = {
  version: 1,
  voice: 'test',
  prompts: [
    { id: 'listening', lang: 'en', file: 'en/listening.mp3', text: "I'm listening." },
    { id: 'listening', lang: 'yo', file: 'yo/listening.mp3', text: 'Mo n gbo.' },
    { id: 'settled', lang: 'en', text: 'Done.' },
    { id: 'only_en', lang: 'en', file: 'en/only.mp3', text: 'English only.' },
  ],
}

describe('resolvePrompt', () => {
  it('uses the audio file for the active language', () => {
    const r = resolvePrompt(manifest, 'listening', 'yo')
    expect(r).toMatchObject({ kind: 'file', entry: { lang: 'yo' } })
  })
  it('falls back to English audio when the language lacks the id', () => {
    const r = resolvePrompt(manifest, 'only_en', 'yo')
    expect(r).toMatchObject({ kind: 'file', entry: { lang: 'en' } })
  })
  it('speaks the manifest text when the file is missing', () => {
    expect(resolvePrompt(manifest, 'settled', 'en')).toEqual({ kind: 'text', text: 'Done.', lang: 'en' })
  })
  it('speaks the text when the file exists in the manifest but was not decoded', () => {
    const r = resolvePrompt(manifest, 'listening', 'en', () => false)
    expect(r).toEqual({ kind: 'text', text: "I'm listening.", lang: 'en' })
  })
  it('returns null for unknown ids or no manifest', () => {
    expect(resolvePrompt(manifest, 'nope', 'en')).toBeNull()
    expect(resolvePrompt(null, 'listening', 'en')).toBeNull()
  })
})
