import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

const tokens = readFileSync('src/styles/tokens.css', 'utf8')
const themes = readFileSync('src/styles/themes.css', 'utf8')

function lum(hex: string): number {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4))
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
}
export const ratio = (a: string, b: string) => {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p)
  return (x + 0.05) / (y + 0.05)
}

/** Pull `--name: #hex` pairs out of a CSS block selected by a marker string. */
function block(css: string, marker: string): Record<string, string> {
  const start = css.indexOf(marker)
  const end = css.indexOf('}', start)
  const out: Record<string, string> = {}
  for (const m of css.slice(start, end).matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{6})/g)) out[m[1]] = m[2]
  return out
}

const dark = block(tokens, ':root {')
const light = block(tokens, ":root[data-theme='light'] {")
const hcDark = block(themes, ":root[data-contrast='high'] {")
const hcLight = block(themes, ":root[data-contrast='high'][data-theme='light']")

const sets: Array<[string, Record<string, string>, Record<string, string>]> = [
  ['dark', dark, dark],
  ['light', light, light],
  ['high-contrast dark', { ...dark, ...hcDark }, hcDark],
  ['high-contrast light', { ...light, ...hcLight }, hcLight],
]

describe.each(sets)('contrast: %s', (_name, t) => {
  it('body and muted text reach AAA 7:1 on bg and surface', () => {
    for (const bg of ['bg', 'surface', 'surface-raised']) {
      expect(ratio(t.text, t[bg]), `text on ${bg}`).toBeGreaterThanOrEqual(7)
      expect(ratio(t['text-muted'], t[bg]), `text-muted on ${bg}`).toBeGreaterThanOrEqual(7)
    }
  })
  it('status and accent colours reach 4.5:1 on bg and surface', () => {
    for (const fg of ['accent', 'success', 'warning', 'danger', 'simulated']) {
      for (const bg of ['bg', 'surface']) expect(ratio(t[fg], t[bg]), `${fg} on ${bg}`).toBeGreaterThanOrEqual(4.5)
    }
  })
  it('text on accent buttons reaches 4.5:1', () => {
    expect(ratio(t['on-accent'], t.accent)).toBeGreaterThanOrEqual(4.5)
  })
})
