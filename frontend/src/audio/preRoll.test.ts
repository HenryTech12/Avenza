import { describe, expect, it } from 'vitest'
import { PreRoll, framesForMs } from './preRoll'

const f = (n: number) => new Uint8Array([n]).buffer

describe('PreRoll', () => {
  it('keeps only the most recent frames', () => {
    const p = new PreRoll(3)
    ;[1, 2, 3, 4, 5].forEach((n) => p.push(f(n)))
    expect(p.length).toBe(3)
    expect(p.drain().map((b) => new Uint8Array(b)[0])).toEqual([3, 4, 5])
  })
  it('is empty after drain/clear', () => {
    const p = new PreRoll(3)
    p.push(f(1))
    p.drain()
    expect(p.length).toBe(0)
    p.push(f(2))
    p.clear()
    expect(p.length).toBe(0)
  })
  it('computes frame counts', () => {
    expect(framesForMs(300)).toBe(15)
  })
})
